from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from .models import UserProfile, Land, Proposal, Bond, BuilderProfile
from .forms import LandForm, ProposalForm
from django.contrib.auth.models import User
from django.utils import timezone

class AddLandView(LoginRequiredMixin, View):
    def get(self, request):
        form = LandForm()
        return render(request, 'potential_app/add_land.html', {'form': form})
    
    def post(self, request):
        form = LandForm(request.POST, request.FILES)
        if form.is_valid():
            land = form.save(commit=False)
            land.owner = request.user
            land.save()
            messages.success(request, "Land added successfully!")
            return redirect('dashboard')
        return render(request, 'potential_app/add_land.html', {'form': form})

class BuilderListView(View):
    def get(self, request):
        builders = BuilderProfile.objects.all()
        return render(request, 'potential_app/builder_list.html', {'builders': builders})

class SubmitProposalView(LoginRequiredMixin, View):
    def get(self, request, builder_id):
        builder = get_object_or_404(User, id=builder_id)
        # Get current user's lands
        lands = Land.objects.filter(owner=request.user)
        form = ProposalForm()
        return render(request, 'potential_app/submit_proposal.html', {'builder': builder, 'lands': lands, 'form': form})

    def post(self, request, builder_id):
        builder = get_object_or_404(User, id=builder_id)
        land_id = request.POST.get('land_id')
        form = ProposalForm(request.POST) # Contains message
        
        if form.is_valid() and land_id:
            try:
                # We need to link to LandAnalysis mostly due to previous model structure, 
                # but let's assume we can link to LAND if we updated the model. 
                # Wait, I need to check if I updated Proposal reference to Land in step 171.
                # In Step 171 I wrote: `land_analysis = models.ForeignKey(LandAnalysis...)`
                # I should probably auto-create a LandAnalysis stub or update the Proposal model to link to Land.
                # For now, I will create a dummy LandAnalysis from the Land to satisfy the FK.
                
                land = get_object_or_404(Land, id=land_id, owner=request.user)
                
                # Check if analysis exists or create stub
                from .models import LandAnalysis
                analysis, created = LandAnalysis.objects.get_or_create(
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
            except Exception as e:
                 messages.error(request, f"Error creating proposal: {str(e)}")
        else:
             messages.error(request, "Please select a land and enter a message.")
             
        lands = Land.objects.filter(owner=request.user)
        return render(request, 'potential_app/submit_proposal.html', {'builder': builder, 'lands': lands, 'form': form})

class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        # Determine role (safe check)
        is_builder = False
        if hasattr(request.user, 'profile') and request.user.profile.role == 'builder':
            is_builder = True
        elif hasattr(request.user, 'builder_profile'): # fallback check
            is_builder = True
            
        context = {
            'is_builder': is_builder,
        }
        
        if is_builder:
            # Proposals received
            proposals = Proposal.objects.filter(builder=request.user).order_by('-created_at')
            context['proposals'] = proposals
            return render(request, 'potential_app/dashboard_builder.html', context)
        else:
            # Landowner Dashboard
            my_lands = Land.objects.filter(owner=request.user)
            # Proposals sent
            proposals = Proposal.objects.filter(landowner=request.user).order_by('-created_at')
            
            context['proposals'] = proposals
            context['lands'] = my_lands
            return render(request, 'potential_app/dashboard_landowner.html', context)

class ProposalDetailView(LoginRequiredMixin, View):
    def get(self, request, proposal_id):
        proposal = get_object_or_404(Proposal, id=proposal_id)
        
        # Security
        if request.user != proposal.builder and request.user != proposal.landowner:
             messages.error(request, "Access denied.")
             return redirect('dashboard')
             
        return render(request, 'potential_app/proposal_detail.html', {'proposal': proposal})

    # def post(self, request, proposal_id):
    #     proposal = get_object_or_404(Proposal, id=proposal_id)
    #     action = request.POST.get('action')
        
    #     # 1. Builder Actions
    #     if request.user == proposal.builder:
    #         if action == 'accept':
    #             proposal.status = 'accepted'
    #             proposal.builder_response_message = "Proposal Accepted. Waiting for investment decision."
    #             proposal.save()
    #         elif action == 'reject':
    #             proposal.status = 'rejected'
    #             proposal.builder_response_message = "Proposal Rejected."
    #             proposal.save()
                
    #     # 2. Landowner Actions (Investment Choice)
    #     elif request.user == proposal.landowner:
    #         if action == 'choose_self':
    #             proposal.investment_choice = 'self_invest'
    #             proposal.save()
    #             self.create_bond(proposal)
    #         elif action == 'choose_builder':
    #             proposal.investment_choice = 'builder_invest'
    #             proposal.save()
    #             self.create_bond(proposal)
                
    #     return redirect('proposal_detail', proposal_id=proposal.id)

    # def create_bond(self, proposal):
    #     # Create a dummy legal bond
    #     if not hasattr(proposal, 'bond'):
    #         content = f"LEGAL BOND AGREEMENT\n\n" \
    #                   f"Date: {timezone.now()}\n" \
    #                   f"Parties: {proposal.landowner.username} (Landowner) AND {proposal.builder.username} (Builder)\n" \
    #                   f"Land: {proposal.land_analysis.latitude}, {proposal.land_analysis.longitude}\n" \
    #                   f"Investment Model: {proposal.get_investment_choice_display()}\n\n" \
    #                   f"Terms: Use of land for Solar PV plant development..."
            
    #         Bond.objects.create(proposal=proposal, content=content)
    #         messages.success(self.request, "Bond generated successfully!")
    def post(self, request, proposal_id):
        proposal = get_object_or_404(Proposal, id=proposal_id)
        action = request.POST.get('action')

        if request.user == proposal.builder:
            if action == 'accept':
                proposal.status = 'accepted'
                proposal.builder_response_message = "Proposal Accepted. Waiting for investment decision."
                proposal.save()

            elif action == 'reject':
                proposal.status = 'rejected'
                proposal.builder_response_message = "Proposal Rejected."
                proposal.save()

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
        if not Bond.objects.filter(proposal=proposal).exists():
            content = f"""LEGAL BOND AGREEMENT

    Date: {timezone.now()}
    Parties: {proposal.landowner.username} (Landowner)
    AND {proposal.builder.username} (Builder)

    Land: {proposal.land_analysis.latitude}, {proposal.land_analysis.longitude}
    Investment Model: {proposal.get_investment_choice_display()}
    """
            Bond.objects.create(proposal=proposal, content=content)
            messages.success(request, "Bond generated successfully!")

