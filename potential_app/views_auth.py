from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages

from .forms import CustomUserCreationForm, BuilderProfileForm
from .models import (
    UserProfile,
    BuilderProfile,
    BuilderPortfolioImage
)

# =====================================================
# LANDOWNER SIGNUP
# =====================================================
def signup_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()

            UserProfile.objects.update_or_create(
                user=user,
                defaults={'role': 'landowner'}
            )

            login(request, user)
            messages.success(request, f"Welcome, Landowner {user.username}!")
            return redirect('index')

        messages.error(request, "Please correct the errors below.")

    else:
        form = CustomUserCreationForm()

    return render(request, 'potential_app/signup.html', {
        'form': form,
        'user_type': 'Landowner'
    })


# =====================================================
# BUILDER SIGNUP (🔥 CORRECT FK HANDLING)
# =====================================================
def builder_signup_view(request):
    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        profile_form = BuilderProfileForm(request.POST)

        uploaded_images = request.FILES.getlist('images')

        if user_form.is_valid() and profile_form.is_valid():
            # 1️⃣ Create user
            user = user_form.save()

            # 2️⃣ Assign role
            UserProfile.objects.update_or_create(
                user=user,
                defaults={'role': 'builder'}
            )

            # 3️⃣ Create builder profile
            builder_profile = profile_form.save(commit=False)
            builder_profile.user = user
            builder_profile.save()

            # 4️⃣ Save portfolio images (FK style ✅)
            for image in uploaded_images:
                BuilderPortfolioImage.objects.create(
                    builder=builder_profile,
                    image=image
                )

            # 5️⃣ Login
            login(request, user)
            messages.success(request, f"Welcome, Builder {user.username}!")
            return redirect('dashboard')

        messages.error(request, "Please correct the errors below.")

    else:
        user_form = CustomUserCreationForm()
        profile_form = BuilderProfileForm()

    return render(request, 'potential_app/signup_builder.html', {
        'user_form': user_form,
        'profile_form': profile_form
    })


# =====================================================
# LOGIN
# =====================================================
def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            user = authenticate(
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password']
            )

            if user:
                login(request, user)
                role = user.profile.get_role_display()
                messages.success(request, f"Logged in as {role}")
                return redirect('index')

        messages.error(request, "Invalid username or password.")

    else:
        form = AuthenticationForm()

    return render(request, 'potential_app/login.html', {'form': form})


# =====================================================
# LOGOUT
# =====================================================
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('index')
