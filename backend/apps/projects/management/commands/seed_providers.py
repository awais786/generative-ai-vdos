from django.core.management.base import BaseCommand

from apps.core.models import Provider
from apps.projects.choices import Capability
from apps.projects.models import LLMModel

PROVIDERS = [
    {"code": "openai",    "name": "OpenAI"},
    {"code": "anthropic", "name": "Anthropic"},
    {"code": "google",    "name": "Google"},
    {"code": "dashscope", "name": "DashScope (Alibaba)"},
    {"code": "litellm",   "name": "LiteLLM"},
    {"code": "replicate", "name": "Replicate"},
    {"code": "pexels",    "name": "Pexels"},
]


def _model(provider, cap, model_id, name, free=False, default=False):
    return {
        "provider": provider, "capability": cap, "model_id": model_id,
        "display_name": name, "is_free": free, "is_default": default,
    }


MODELS = [
    # Plan models
    _model("google", Capability.PLAN, "gemini-3.1-flash-lite", "Gemini Flash Lite (free)", free=True, default=True),
    _model("google", Capability.PLAN, "gemini-2.5-flash", "Gemini Flash"),
    _model("openai", Capability.PLAN, "gpt-4o-mini", "GPT-4o Mini"),
    _model("anthropic", Capability.PLAN, "claude-haiku-4-5", "Claude Haiku"),
    _model("litellm", Capability.PLAN, "groq/llama-3.3-70b", "Llama 3.3 70B (LiteLLM)", free=True),
    # Image models
    _model("dashscope", Capability.IMAGE, "qwen-image-2.0", "Qwen Image 2.0 (free)", free=True, default=True),
    _model("replicate", Capability.IMAGE, "flux-schnell", "Flux Schnell", free=True),
    _model("pexels", Capability.IMAGE, "pexels", "Pexels Stock", free=True),
    _model("openai", Capability.IMAGE, "gpt-image-1", "GPT Image 1"),
    # Video models
    _model("dashscope", Capability.VIDEO, "wan2.2-i2v-flash", "Wan Flash", free=True, default=True),
    _model("dashscope", Capability.VIDEO, "wan2.1-i2v-turbo", "Wan Turbo"),
    _model("dashscope", Capability.VIDEO, "wan2.1-i2v-plus", "Wan Plus"),
]


class Command(BaseCommand):
    help = "Seed Provider and LLMModel tables (idempotent)"

    def handle(self, *args, **options):
        provider_map = {}
        for p in PROVIDERS:
            obj, created = Provider.objects.update_or_create(
                code=p["code"], defaults={"name": p["name"]},
            )
            provider_map[p["code"]] = obj
            self.stdout.write(f"  {'Created' if created else 'Updated'} provider: {obj.name}")

        for m in MODELS:
            provider = provider_map[m["provider"]]
            obj, created = LLMModel.objects.update_or_create(
                provider=provider, capability=m["capability"], model_id=m["model_id"],
                defaults={
                    "display_name": m["display_name"],
                    "is_free": m["is_free"],
                    "is_default": m["is_default"],
                },
            )
            self.stdout.write(f"  {'Created' if created else 'Updated'} model: {obj}")

        self.stdout.write(self.style.SUCCESS(
            f"Done — {Provider.objects.count()} providers, {LLMModel.objects.count()} models"
        ))
