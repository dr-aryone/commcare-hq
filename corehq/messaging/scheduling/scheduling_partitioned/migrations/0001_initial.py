# -*- coding: utf-8 -*-
# Generated by Django 1.9.12 on 2017-02-23 20:48
from __future__ import unicode_literals

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ScheduleInstance',
            fields=[
                ('timed_schedule_id', models.IntegerField(db_index=True, null=True)),
                ('alert_schedule_id', models.IntegerField(db_index=True, null=True)),
                ('schedule_instance_id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('domain', models.CharField(max_length=126)),
                ('recipient_type', models.CharField(max_length=126)),
                ('recipient_id', models.CharField(max_length=126)),
                ('start_date', models.DateField(null=True)),
                ('current_event_num', models.IntegerField()),
                ('schedule_iteration_num', models.IntegerField()),
                ('next_event_due', models.DateTimeField()),
                ('active', models.BooleanField()),
            ],
            options={
                'db_table': 'scheduling_scheduleinstance',
            },
        ),
        migrations.AlterIndexTogether(
            name='scheduleinstance',
            index_together=set([('active', 'next_event_due'), ('domain', 'active', 'next_event_due')]),
        ),
    ]
