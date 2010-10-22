from django.db.models import sql
from django.db.models.loading import cache
from django.test import TestCase

from models import A, B, C, D, E, F


class DeleteTests(TestCase):
    def clear_rel_obj_caches(self, *models):
        for m in models:
            if hasattr(m._meta, '_related_objects_cache'):
                del m._meta._related_objects_cache

    def order_models(self, *models):
        cache.app_models["delete"].keyOrder = models

    def setUp(self):
        self.order_models("a", "b", "c", "d", "e", "f")
        self.clear_rel_obj_caches(A, B, C, D, E, F)

    def tearDown(self):
        self.order_models("a", "b", "c", "d", "e", "f")
        self.clear_rel_obj_caches(A, B, C, D, E, F)

