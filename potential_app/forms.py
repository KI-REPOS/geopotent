from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import LandAnalysis, BuilderProfile, Proposal, Land, BuilderProfile, Proposal, Land

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text='Required. Inform a valid email address.')

    class Meta:
        model = User
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user

class LandAnalysisForm(forms.ModelForm):
    class Meta:
        model = LandAnalysis
        fields = [
            'latitude', 'longitude', 'area_m2', 'area_ha', 
            'start_date', 'end_date'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        area_m2 = cleaned_data.get('area_m2')
        area_ha = cleaned_data.get('area_ha')
        
        if not area_m2 and not area_ha:
            raise forms.ValidationError("Please provide either area in m² or hectares.")
        
        return cleaned_data

class AdvancedSettingsForm(forms.ModelForm):
    class Meta:
        model = LandAnalysis
        fields = [
            'pv_efficiency', 'pv_performance_ratio', 'pv_land_coverage', 'pv_system_efficiency',
            'wind_rated_power_kw', 'wind_rotor_diameter_m', 'wind_hub_height_m',
            'wind_cut_in_ms', 'wind_rated_ws_ms', 'wind_cut_out_ms', 'wind_alpha', 'wind_system_efficiency',
            'dc_voltage'
        ]

class BuilderProfileForm(forms.ModelForm):
    class Meta:
        model = BuilderProfile
        fields = ['company_name', 'description', 'experience_years', 'portfolio_images']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

class LandForm(forms.ModelForm):
    class Meta:
        model = Land
        fields = ['name', 'latitude', 'longitude', 'area_m2', 'address', 'proof_document']
        widgets = {
            'latitude': forms.NumberInput(attrs={
                'step': 'any',
                'placeholder': 'e.g. 12.9716'
            }),
            'longitude': forms.NumberInput(attrs={
                'step': 'any',
                'placeholder': 'e.g. 77.5946'
            }),
            'area_m2': forms.NumberInput(attrs={
                'step': 'any'
            }),
        }
        
class ProposalForm(forms.ModelForm):
    class Meta:
        model = Proposal
        fields = ['message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describe your proposal...'}),
        }