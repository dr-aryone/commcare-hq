# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-07-11 12:26
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('phonelog', '0012_server_date_not_null'),
    ]

    operations = [
        migrations.DeleteModel(
            name='OldDeviceReportEntry',
        ),
    ]
