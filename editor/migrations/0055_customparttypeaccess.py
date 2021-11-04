# Generated by Django 3.1.8 on 2021-11-03 20:02

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import editor.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('editor', '0054_auto_20210816_1144'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomPartTypeAccess',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('access', models.CharField(choices=[('view', 'Can view'), ('edit', 'Can edit')], default='view', max_length=6)),
                ('custom_part_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='access', to='editor.customparttype')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='custom_part_type_accesses', to=settings.AUTH_USER_MODEL)),
            ],
            bases=(models.Model, editor.models.TimelineMixin),
        ),
    ]
