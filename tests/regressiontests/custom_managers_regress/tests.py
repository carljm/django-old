from django.test import TestCase

from models import (
    RelatedModel, RestrictedModel, OneToOneRestrictedModel,
    ManyToManyRestrictedModel)

class CustomManagersRegressTestCase(TestCase):
    def test_filtered_default_manager(self):
        """Even though the default manager filters out some records,
        we must still be able to save (particularly, save by updating
        existing records) those filtered instances. This is a
        regression test for #8990, #9527"""
        related = RelatedModel.objects.create(name="xyzzy")
        obj = RestrictedModel.objects.create(name="hidden", related=related)
        obj.name = "still hidden"
        obj.save()

        # If the hidden object wasn't seen during the save process,
        # there would now be two objects in the database.
        self.assertEqual(RestrictedModel.plain_manager.count(), 1)

    def test_delete_related_on_filtered_manager(self):
        """Deleting related objects should also not be distracted by a
        restricted manager on the related object. This is a regression
        test for #2698."""
        related = RelatedModel.objects.create(name="xyzzy")

        for name, public in (('one', True), ('two', False), ('three', False)):
            RestrictedModel.objects.create(name=name, is_public=public, related=related)

        obj = RelatedModel.objects.get(name="xyzzy")
        obj.delete()

        # All of the RestrictedModel instances should have been
        # deleted, since they *all* pointed to the RelatedModel. If
        # the default manager is used, only the public one will be
        # deleted.
        self.assertEqual(len(RestrictedModel.plain_manager.all()), 0)

    def test_delete_one_to_one_manager(self):
        # The same test case as the last one, but for one-to-one
        # models, which are implemented slightly different internally,
        # so it's a different code path.
        obj = RelatedModel.objects.create(name="xyzzy")
        OneToOneRestrictedModel.objects.create(name="foo", is_public=False, related=obj)
        obj = RelatedModel.objects.get(name="xyzzy")
        obj.delete()
        self.assertEqual(len(OneToOneRestrictedModel.plain_manager.all()), 0)


class UseForRelatedFieldsFKTest(TestCase):
    restricted_model = RestrictedModel
    accessor_name = "restrictedmodel_set"

    def create_restricted_instance(self, **kwargs):
        return self.restricted_model.objects.create(**kwargs)

    def test_use_for_related_false(self):
        """
        Test that when a custom Manager without ``use_for_related_fields =
        True`` is the default manager, it is not used for related object
        queries.

        """
        related = RelatedModel.objects.create(name="Related")
        # create two public instances and one private
        self.create_restricted_instance(
            name="Public One", is_public=True, related=related)
        self.create_restricted_instance(
            name="Public Two", is_public=True, related=related)
        self.create_restricted_instance(
            name="Private", is_public=False, related=related)

        # all three restricted-model instances should show up
        self.assertEqual(getattr(related, self.accessor_name).count(), 3)


class UseForRelatedFieldsM2MTest(UseForRelatedFieldsFKTest):
    restricted_model = ManyToManyRestrictedModel
    accessor_name = "manytomanyrestrictedmodel_set"

    def create_restricted_instance(self, **kwargs):
        related = kwargs.pop("related")
        obj = UseForRelatedFieldsFKTest.create_restricted_instance(
            self, **kwargs)
        obj.related.add(related)
        return obj
