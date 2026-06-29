import apps.projects.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0002_rename_image_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="scene",
            name="audio_path",
            field=models.FileField(
                blank=True, default="", upload_to=apps.projects.models.scene_audio_upload_path
            ),
        ),
        migrations.AddField(
            model_name="scene",
            name="voice",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="scene",
            name="voice_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("RUNNING", "Running"),
                    ("DONE", "Done"),
                    ("FAILED", "Failed"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="scene",
            name="words_path",
            field=models.FileField(
                blank=True, default="", upload_to=apps.projects.models.scene_audio_upload_path
            ),
        ),
    ]
