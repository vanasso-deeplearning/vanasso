from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0009_remove_order_from_cashbookcategory'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='code',
            field=models.CharField(blank=True, max_length=10, verbose_name='계정코드'),
        ),
    ]
