import json
import traceback
import logging
import os

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views import View
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders

from .forms import LandAnalysisForm, AdvancedSettingsForm
from .models import LandAnalysis

from utils.soil_analysis import (
    get_soil_data,
    recommend_crops,
    estimate_agri_revenue
)
from utils.energy_estimation import (
    estimate_energy_potential,
    plot_to_base64,
    calculate_mixed_potential
)

# -------------------------------------------------
# Logging
# -------------------------------------------------
logger = logging.getLogger(__name__)


# -------------------------------------------------
# PDF helper
# -------------------------------------------------
def link_callback(uri, rel):
    result = finders.find(uri)
    if result:
        if not isinstance(result, (list, tuple)):
            result = [result]
        return os.path.realpath(result[0])
    return uri


# =================================================
# VIEWS
# =================================================

class IndexView(View):
    def get(self, request):
        return render(request, "potential_app/index.html")


class AnalysisInputView(View):
    def get(self, request):
        return render(
            request,
            "potential_app/input_form.html",
            {
                "form": LandAnalysisForm(),
                "advanced_form": AdvancedSettingsForm(),
            },
        )

    def post(self, request):
        form = LandAnalysisForm(request.POST)
        advanced_form = AdvancedSettingsForm(request.POST)

        if form.is_valid() and advanced_form.is_valid():
            analysis = form.save(commit=False)

            for field in advanced_form.fields:
                setattr(analysis, field, advanced_form.cleaned_data[field])

            analysis.save()
            return redirect("process_analysis", analysis_id=analysis.id)

        return render(
            request,
            "potential_app/input_form.html",
            {"form": form, "advanced_form": advanced_form},
        )


class ProcessAnalysisView(View):
    def get(self, request, analysis_id):
        try:
            analysis = LandAnalysis.objects.get(id=analysis_id)

            # -----------------------------
            # SOIL DATA (SAFE STRUCTURE)
            # -----------------------------
            raw_soil = get_soil_data(analysis.latitude, analysis.longitude) or {}

            soil_data = {}
            for prop, value in raw_soil.items():
                if isinstance(value, dict):
                    soil_data[prop] = value
                else:
                    soil_data[prop] = {
                        "0-5cm": value,
                        "5-15cm": value,
                        "15-30cm": value,
                    }

            analysis.soil_data = soil_data

            # -----------------------------
            # CROP RECOMMENDATIONS
            # -----------------------------
            try:
                crop_recommendations = recommend_crops(soil_data) or []
            except Exception:
                crop_recommendations = []

            analysis.crop_recommendations = crop_recommendations

            # -----------------------------
            # ENERGY ESTIMATION
            # -----------------------------
            try:
                area_m2 = (
                    analysis.area_m2
                    or (analysis.area_ha * 10000 if analysis.area_ha else 0)
                )
                area_ha = area_m2 / 10000 if area_m2 else 0

                energy_results = estimate_energy_potential(
                    lat=analysis.latitude,
                    lon=analysis.longitude,
                    start_date=analysis.start_date.strftime("%Y-%m-%d"),
                    end_date=analysis.end_date.strftime("%Y-%m-%d"),
                    area_m2=area_m2,
                    pv_config={
                        "efficiency": analysis.pv_efficiency,
                        "performance_ratio": analysis.pv_performance_ratio,
                        "land_coverage": analysis.pv_land_coverage,
                        "system_efficiency": analysis.pv_system_efficiency,
                    },
                    wind_config={
                        "rated_power_kw": analysis.wind_rated_power_kw,
                        "rotor_diameter_m": analysis.wind_rotor_diameter_m,
                        "hub_height_m": analysis.wind_hub_height_m,
                        "cut_in_ms": analysis.wind_cut_in_ms,
                        "rated_ws_ms": analysis.wind_rated_ws_ms,
                        "cut_out_ms": analysis.wind_cut_out_ms,
                        "alpha": analysis.wind_alpha,
                        "system_efficiency": analysis.wind_system_efficiency,
                    },
                    dc_voltage=analysis.dc_voltage,
                ) or {}

            except Exception as e:
                logger.error("Energy estimation failed")
                logger.error(traceback.format_exc())
                energy_results = {}

            # -----------------------------
            # NORMALIZE ENERGY RESULTS
            # -----------------------------
            energy_results.setdefault("total_energy_kwh", 0)
            energy_results.setdefault("pv_energy_kwh", 0)
            energy_results.setdefault("wind_energy_kwh", 0)
            energy_results.setdefault("total_revenue", 0)
            energy_results.setdefault("monthly_breakdown", [])
            energy_results.setdefault("hourly_plot", "")
            energy_results.setdefault("daily_plot", "")

            # Normalize monthly breakdown
            normalized_months = []
            for item in energy_results.get("monthly_breakdown", []):
                normalized_months.append({
                    "month": item.get("month", ""),
                    "energy": item.get(
                        "energy",
                        item.get("pv_energy_kwh", 0) + item.get("wind_energy_kwh", 0)
                    ),
                    "revenue": item.get(
                        "revenue",
                        item.get("revenue_inr", 0)
                    ),
                    "pv_energy_kwh": item.get("pv_energy_kwh", 0),
                    "wind_energy_kwh": item.get("wind_energy_kwh", 0),
                })

            energy_results["monthly_breakdown"] = normalized_months

            # -----------------------------
            # AGRI + MIXED REVENUE
            # -----------------------------
            try:
                agri_revenue = estimate_agri_revenue(crop_recommendations, area_ha) or {
                    "details": []
                }
            except Exception:
                agri_revenue = {"details": []}

            try:
                mixed_analysis = calculate_mixed_potential(
                    energy_results, agri_revenue, area_ha
                ) or {"scenarios": [], "best_scenario": {}}
            except Exception:
                mixed_analysis = {"scenarios": [], "best_scenario": {}}

            energy_results["agri_revenue"] = agri_revenue
            energy_results["mixed_analysis"] = mixed_analysis

            analysis.energy_results = energy_results
            analysis.save()

            return redirect("results", analysis_id=analysis.id)

        except LandAnalysis.DoesNotExist:
            return redirect("index")
        except Exception as e:
            logger.error("ProcessAnalysis failed")
            logger.error(traceback.format_exc())
            return redirect("index")


class ResultsView(View):
    def get(self, request, analysis_id):
        try:
            analysis = LandAnalysis.objects.get(id=analysis_id)

            energy_results = analysis.energy_results or {}
            energy_results.setdefault("agri_revenue", {"details": []})
            energy_results.setdefault("mixed_analysis", {})
            energy_results.setdefault("monthly_breakdown", [])

            context = {
                "analysis": analysis,
                "soil_data": analysis.soil_data or {},
                "crop_recommendations": analysis.crop_recommendations or [],
                "energy_results": energy_results,
            }
            return render(request, "potential_app/results.html", context)

        except LandAnalysis.DoesNotExist:
            return redirect("index")


class ReportView(View):
    def get(self, request, analysis_id):
        try:
            analysis = LandAnalysis.objects.get(id=analysis_id)
            return render(
                request,
                "potential_app/report_template.html",
                {
                    "analysis": analysis,
                    "soil_data": analysis.soil_data or {},
                    "crop_recommendations": analysis.crop_recommendations or [],
                    "energy_results": analysis.energy_results or {},
                },
            )
        except LandAnalysis.DoesNotExist:
            return redirect("index")


class ReportDownloadView(View):
    def get(self, request, analysis_id):
        import matplotlib.pyplot as plt
        from xhtml2pdf import pisa

        try:
            analysis = LandAnalysis.objects.get(id=analysis_id)
            energy_results = analysis.energy_results or {}

            fig, ax = plt.subplots(figsize=(10, 6))
            months = [m["month"] for m in energy_results.get("monthly_breakdown", [])]
            revenue = [m["revenue"] for m in energy_results.get("monthly_breakdown", [])]

            ax.plot(months, revenue, marker="o")
            ax.set_title("Monthly Revenue Projection")
            ax.set_ylabel("Revenue (₹)")
            ax.grid(True)

            plot_img = plot_to_base64(fig)
            plt.close(fig)

            context = {
                "analysis": analysis,
                "soil_data": analysis.soil_data or {},
                "crop_recommendations": analysis.crop_recommendations or [],
                "energy_results": energy_results,
                "detailed_plots": plot_img,
            }

            html = render_to_string("potential_app/report_template.html", context)
            response = HttpResponse(content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="report_{analysis_id}.pdf"'

            pisa.CreatePDF(html, dest=response, link_callback=link_callback)
            return response

        except Exception:
            logger.error("PDF generation failed")
            logger.error(traceback.format_exc())
            return HttpResponse("PDF generation error", status=500)
