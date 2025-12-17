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
from utils.soil_analysis import get_soil_data, recommend_crops, estimate_agri_revenue
from utils.energy_estimation import estimate_energy_potential, plot_to_base64, calculate_mixed_potential

# 🔹 Logging setup
logger = logging.getLogger(__name__)


# 🔹 Helper for static/media files in PDF
def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths for xhtml2pdf
    """
    result = finders.find(uri)
    if result:
        if not isinstance(result, (list, tuple)):
            result = [result]
        path = os.path.realpath(result[0])
        return path
    return uri


# -------------------------------
# VIEWS
# -------------------------------

class IndexView(View):
    def get(self, request):
        return render(request, "potential_app/index.html")


class AnalysisInputView(View):
    def get(self, request):
        form = LandAnalysisForm()
        advanced_form = AdvancedSettingsForm()
        return render(
            request,
            "potential_app/input_form.html",
            {"form": form, "advanced_form": advanced_form},
        )
    # def get(self, request, land_id=None):
    #     form = LandAnalysisForm()
    #     advanced_form = AdvancedSettingsForm()

    #     if land_id:
    #         from .models import Land
    #         land = get_object_or_404(Land, id=land_id, owner=request.user)
    #         form.initial = {
    #             'latitude': land.latitude,
    #             'longitude': land.longitude,
    #             'area_m2': land.area_m2,
    #         }

    def post(self, request):
        form = LandAnalysisForm(request.POST)
        advanced_form = AdvancedSettingsForm(request.POST)

        if form.is_valid() and advanced_form.is_valid():
            analysis = form.save(commit=False)

            # Apply advanced settings
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

            # Soil data
            soil_data = get_soil_data(analysis.latitude, analysis.longitude)
            analysis.soil_data = soil_data

            # Crop recommendations
            crop_recommendations = recommend_crops(soil_data)
            analysis.crop_recommendations = crop_recommendations

            # Energy estimation
            try:
                energy_results = estimate_energy_potential(
                    lat=analysis.latitude,
                    lon=analysis.longitude,
                    start_date=analysis.start_date.strftime("%Y-%m-%d"),
                    end_date=analysis.end_date.strftime("%Y-%m-%d"),
                    area_m2=analysis.area_m2
                    or (analysis.area_ha * 10000 if analysis.area_ha else 0),
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
                )

                if not energy_results or energy_results.get("total_energy_kwh", 0) == 0:
                    logger.warning("⚠️ Energy estimation returned zero. Check API/data.")

                # Agri Revenue
                area_ha = analysis.area_ha or (analysis.area_m2 / 10000.0 if analysis.area_m2 else 0)
                agri_revenue_results = estimate_agri_revenue(crop_recommendations, area_ha)

                # Mixed Potential
                mixed_results = calculate_mixed_potential(energy_results, agri_revenue_results, area_ha)

                # Merge results
                energy_results["agri_revenue"] = agri_revenue_results
                energy_results["mixed_analysis"] = mixed_results

                analysis.energy_results = energy_results

            except Exception as e:
                logger.error(f"Energy estimation failed: {str(e)}")
                logger.error(traceback.format_exc())
                analysis.energy_results = {
                    "total_energy_kwh": 0,
                    "pv_energy_kwh": 0,
                    "wind_energy_kwh": 0,
                    "total_revenue": 0,
                    "monthly_breakdown": [],
                    "hourly_plot": "",
                    "daily_plot": "",
                    "agri_revenue": {},
                    "mixed_analysis": {}
                }

            analysis.save()
            return redirect("results", analysis_id=analysis.id)

        except LandAnalysis.DoesNotExist:
            return redirect("index")
        except Exception as e:
            logger.error(f"Process analysis failed: {str(e)}")
            return redirect("index")


class ResultsView(View):
    def get(self, request, analysis_id):
        try:
            analysis = LandAnalysis.objects.get(id=analysis_id)
            energy_results = analysis.energy_results or {}

            if not isinstance(energy_results, dict):
                energy_results = {}

            # Ensure defaults
            energy_results.setdefault("total_energy_kwh", 0)
            energy_results.setdefault("pv_energy_kwh", 0)
            energy_results.setdefault("wind_energy_kwh", 0)
            energy_results.setdefault("total_revenue", 0)
            energy_results.setdefault("monthly_breakdown", [])
            energy_results.setdefault("hourly_plot", "")
            energy_results.setdefault("daily_plot", "")

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
    """ ✅ Browser view of report (same template as PDF) """
    def get(self, request, analysis_id):
        try:
            analysis = LandAnalysis.objects.get(id=analysis_id)
            context = {
                "analysis": analysis,
                "soil_data": analysis.soil_data or {},
                "crop_recommendations": analysis.crop_recommendations or [],
                "energy_results": analysis.energy_results or {},
            }
            return render(request, "potential_app/report_template.html", context)

        except LandAnalysis.DoesNotExist:
            return redirect("index")


class ReportDownloadView(View):
    """ ✅ Generate downloadable PDF report """
    def get(self, request, analysis_id):
        # 🔹 Lazy imports: only when user actually downloads PDF
        import matplotlib.pyplot as plt
        from xhtml2pdf import pisa

        try:
            analysis = LandAnalysis.objects.get(id=analysis_id)
            energy_results = analysis.energy_results or {}

            # --------------------
            # Create detailed plots
            # --------------------
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))

            # Monthly breakdown
            monthly_breakdown = energy_results.get("monthly_breakdown", [])
            if monthly_breakdown:
                months = [item.get("month", "") for item in monthly_breakdown]
                pv_energy = [item.get("pv_energy_kwh", 0) for item in monthly_breakdown]
                wind_energy = [item.get("wind_energy_kwh", 0) for item in monthly_breakdown]

                ax1.bar(months, pv_energy, label="PV Energy", alpha=0.7, color="orange")
                ax1.bar(months, wind_energy, bottom=pv_energy, label="Wind Energy", alpha=0.7, color="green")
                ax1.set_title("Monthly Energy Generation")
                ax1.set_ylabel("Energy (kWh)")
                ax1.tick_params(axis="x", rotation=45)
                ax1.legend()
                ax1.grid(True, alpha=0.3)

                # Revenue
                revenue = [item.get("revenue_inr", 0) for item in monthly_breakdown]
                ax2.plot(months, revenue, marker="o", color="blue", linewidth=2)
                ax2.set_title("Monthly Revenue Projection")
                ax2.set_ylabel("Revenue (₹)")
                ax2.tick_params(axis="x", rotation=45)
                ax2.grid(True, alpha=0.3)

            # Energy distribution
            pv_energy = energy_results.get("pv_energy_kwh", 0)
            wind_energy = energy_results.get("wind_energy_kwh", 0)
            if pv_energy > 0 or wind_energy > 0:
                labels = ["PV Energy", "Wind Energy"]
                sizes = [pv_energy, wind_energy]
                colors = ["orange", "green"]
                ax3.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%", startangle=90)
                ax3.set_title("Energy Distribution")
                ax3.axis("equal")

            # Soil properties
            soil_data = analysis.soil_data or {}
            if soil_data:
                soil_props = list(soil_data.keys())
                prop_values = [
                    (sum(soil_data[prop].values()) / len(soil_data[prop])) if soil_data[prop] else 0
                    for prop in soil_props
                ]
                ax4.bar(soil_props, prop_values, color=["red", "blue", "green", "purple", "brown"])
                ax4.set_title("Average Soil Properties")
                ax4.tick_params(axis="x", rotation=45)
                ax4.grid(True, alpha=0.3)

            plt.tight_layout()
            detailed_plots = plot_to_base64(fig)
            plt.close(fig)   # ✅ free memory

            # --------------------
            # Prepare context for PDF
            # --------------------
            context = {
                "analysis": analysis,
                "soil_data": soil_data,
                "crop_recommendations": analysis.crop_recommendations or [],
                "energy_results": energy_results,
                "hourly_plot": energy_results.get("hourly_plot", ""),
                "daily_plot": energy_results.get("daily_plot", ""),
                "detailed_plots": detailed_plots,
            }

            # Render HTML → PDF
            html_string = render_to_string("potential_app/report_template.html", context)
            response = HttpResponse(content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="land_analysis_report_{analysis_id}.pdf"'

            pisa_status = pisa.CreatePDF(
                html_string,
                dest=response,
                link_callback=link_callback
            )
            if pisa_status.err:
                return HttpResponse("⚠️ Error generating PDF report", status=500)

            return response

        except LandAnalysis.DoesNotExist:
            return redirect("index")
        except Exception as e:
            logger.error(f"PDF generation failed: {str(e)}")
            logger.error(traceback.format_exc())
            return HttpResponse("⚠️ Error generating PDF report", status=500)
