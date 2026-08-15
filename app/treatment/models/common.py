from datetime import datetime
from datetime import time as dt_time

from django.conf import settings
from django.db import models
from django.utils import timezone

from app.doctors.models import DoctorProfile
from app.users.models import Patient
