from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0003_replaysession_simulatedagenttrade_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='replayevent',
            name='open_price',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='replayevent',
            name='high_price',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='replayevent',
            name='low_price',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='replayevent',
            name='depth_levels',
            field=models.JSONField(default=list),
        ),
    ]
