import os
from unittest.mock import patch, MagicMock
from django.test import TestCase

from apps.absenteeism.services.prediction_service import (
    train_dynamic_model,
    predict_with_dynamic_model,
    consolidated_predictions
)
import pandas as pd
import numpy as np

class PredictionServiceTests(TestCase):
    
    def test_model_path_is_absolute(self):
        from apps.absenteeism.services.prediction_service import MODEL_PATH
        
        # Verify it's an absolute path that correctly points to the services/models directory
        self.assertTrue(os.path.isabs(MODEL_PATH))
        self.assertTrue("apps" in MODEL_PATH)
        self.assertTrue("absenteeism" in MODEL_PATH)
        self.assertTrue("services" in MODEL_PATH)
        self.assertTrue("models" in MODEL_PATH)
        self.assertTrue(MODEL_PATH.endswith("dynamic_absenteeism_model.pkl"))
