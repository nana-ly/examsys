from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exam_core', '0004_examrecord_tab_switch_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='exampaper',
            name='end_time',
            field=models.DateTimeField(blank=True, null=True, verbose_name='结束时间'),
        ),
        migrations.AddField(
            model_name='exampaper',
            name='pass_score',
            field=models.DecimalField(decimal_places=1, default=60, max_digits=5, verbose_name='及格分'),
        ),
    ]
