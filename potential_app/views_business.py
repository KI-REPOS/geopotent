from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.models import User

from .models import (
    UserProfile,
    Land,
    Proposal,
    Bond,
    BuilderProfile,
    LandAnalysis
)
from .forms import LandForm, ProposalForm


# =====================================================
# ADD LAND (LANDOWNER ONLY)
# =====================================================
class AddLandView(LoginRequiredMixin, View):
    def get(self, request):
        if request.user.profile.role != 'landowner':
            messages.error(request, "Only landowners can add land.")
            return redirect('dashboard')

        return render(request, 'potential_app/add_land.html', {
            'form': LandForm()
        })

    def post(self, request):
        if request.user.profile.role != 'landowner':
            messages.error(request, "Only landowners can add land.")
            return redirect('dashboard')

        form = LandForm(request.POST, request.FILES)
        if form.is_valid():
            land = form.save(commit=False)
            land.owner = request.user
            land.save()
            messages.success(request, "Land added successfully!")
            return redirect('dashboard')

        return render(request, 'potential_app/add_land.html', {'form': form})


# =====================================================
# BUILDER LIST
# =====================================================
class BuilderListView(View):
    def get(self, request):
        builders = BuilderProfile.objects.select_related('user').all()
        return render(request, 'potential_app/builder_list.html', {
            'builders': builders
        })


# =====================================================
# SUBMIT PROPOSAL (LANDOWNER ONLY)
# =====================================================
class SubmitProposalView(LoginRequiredMixin, View):
    def get(self, request, builder_id):
        if request.user.profile.role != 'landowner':
            messages.error(request, "Only landowners can submit proposals.")
            return redirect('dashboard')

        builder = get_object_or_404(User, id=builder_id)
        lands = Land.objects.filter(owner=request.user)

        return render(request, 'potential_app/submit_proposal.html', {
            'builder': builder,
            'lands': lands,
            'form': ProposalForm()
        })

    def post(self, request, builder_id):
        if request.user.profile.role != 'landowner':
            messages.error(request, "Only landowners can submit proposals.")
            return redirect('dashboard')

        builder = get_object_or_404(User, id=builder_id)
        land_id = request.POST.get('land_id')
        form = ProposalForm(request.POST)

        if not land_id or not form.is_valid():
            messages.error(request, "Please select a land and enter a message.")
            return redirect(request.path)

        land = get_object_or_404(Land, id=land_id, owner=request.user)

        # Create or reuse analysis safely
        analysis, _ = LandAnalysis.objects.get_or_create(
            land=land,
            defaults={
                'latitude': land.latitude,
                'longitude': land.longitude,
                'start_date': timezone.now().date(),
                'end_date': timezone.now().date(),
            }
        )

        Proposal.objects.create(
            landowner=request.user,
            builder=builder,
            land_analysis=analysis,
            message=form.cleaned_data['message'],
            status='pending_builder'
        )

        messages.success(request, f"Proposal sent to {builder.username}!")
        return redirect('dashboard')


# =====================================================
# DASHBOARD
# =====================================================
class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        role = request.user.profile.role

        if role == 'builder':
            proposals = Proposal.objects.filter(
                builder=request.user
            ).select_related('landowner', 'land_analysis').order_by('-created_at')

            return render(request, 'potential_app/dashboard_builder.html', {
                'is_builder': True,
                'proposals': proposals
            })

        # LANDOWNER DASHBOARD
        lands = Land.objects.filter(owner=request.user)
        proposals = Proposal.objects.filter(
            landowner=request.user
        ).select_related('builder', 'land_analysis').order_by('-created_at')

        return render(request, 'potential_app/dashboard_landowner.html', {
            'is_builder': False,
            'lands': lands,
            'proposals': proposals
        })


# =====================================================
# PROPOSAL DETAIL + ACTIONS
# =====================================================
class ProposalDetailView(LoginRequiredMixin, View):
    def get(self, request, proposal_id):
        proposal = get_object_or_404(Proposal, id=proposal_id)

        if request.user not in [proposal.builder, proposal.landowner]:
            messages.error(request, "Access denied.")
            return redirect('dashboard')

        return render(request, 'potential_app/proposal_detail.html', {
            'proposal': proposal
        })

    def post(self, request, proposal_id):
        proposal = get_object_or_404(Proposal, id=proposal_id)
        action = request.POST.get('action')

        # BUILDER ACTIONS
        if request.user == proposal.builder:
            if action == 'accept':
                proposal.status = 'accepted'
                proposal.builder_response_message = "Proposal accepted."
            elif action == 'reject':
                proposal.status = 'rejected'
                proposal.builder_response_message = "Proposal rejected."
            proposal.save()

        # LANDOWNER ACTIONS
        elif request.user == proposal.landowner:
            if action == 'choose_self':
                proposal.investment_choice = 'self_invest'
                proposal.save()
                self.create_bond(request, proposal)

            elif action == 'choose_builder':
                proposal.investment_choice = 'builder_invest'
                proposal.save()
                self.create_bond(request, proposal)

        return redirect('proposal_detail', proposal_id=proposal.id)

    def create_bond(self, request, proposal):
        if hasattr(proposal, 'bond'):
            return

        content = (
            f"LEGAL BOND AGREEMENT\n\n"
            f"Date: {timezone.now()}\n"
            f"Landowner: {proposal.landowner.username}\n"
            f"Builder: {proposal.builder.username}\n"
            f"Land Coordinates: {proposal.land_analysis.latitude}, "
            f"{proposal.land_analysis.longitude}\n"
            f"Investment Model: {proposal.get_investment_choice_display()}\n\n"
            f"Terms: Land usage for solar PV development..."
        )

        Bond.objects.create(proposal=proposal, content=content)
        messages.success(request, "Bond generated successfully!")
