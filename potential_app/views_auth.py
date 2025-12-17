from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from .forms import CustomUserCreationForm, BuilderProfileForm
from .models import UserProfile, BuilderProfile

def signup_view(request):
    """Sigup for Landowners (default)"""
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Ensure profile exists and set role
            if not hasattr(user, 'profile'):
                UserProfile.objects.create(user=user, role='landowner')
            else:
                user.profile.role = 'landowner'
                user.profile.save()
            
            login(request, user)
            messages.success(request, f"Welcome, Landowner {user.username}!")
            return redirect('index')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CustomUserCreationForm()
    return render(request, 'potential_app/signup.html', {'form': form, 'user_type': 'Landowner'})

def builder_signup_view(request):
    """Signup for Builders"""
    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        profile_form = BuilderProfileForm(request.POST, request.FILES)
        
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save()
            
            # Update UserProfile role
            if not hasattr(user, 'profile'):
                UserProfile.objects.create(user=user, role='builder')
            else:
                user.profile.role = 'builder'
                user.profile.save()
            
            # Create BuilderProfile
            builder_profile = profile_form.save(commit=False)
            builder_profile.user = user
            builder_profile.save()
            
            login(request, user)
            messages.success(request, f"Welcome, Builder {user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        user_form = CustomUserCreationForm()
        profile_form = BuilderProfileForm()
        
    return render(request, 'potential_app/signup_builder.html', {
        'user_form': user_form, 
        'profile_form': profile_form
    })

def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                role = "User"
                if hasattr(user, 'profile'):
                    role = user.profile.get_role_display()
                messages.info(request, f"You are now logged in as {role} {username}.")
                return redirect('index')
            else:
                messages.error(request, "Invalid username or password.")
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'potential_app/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.info(request, "You have successfully logged out.")
    return redirect('index')
