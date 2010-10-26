from django.db import models, IntegrityError
from django.test import TestCase, skipUnlessDBFeature

from modeltests.on_delete.models import (R, S, T, U, A, M, MR, MRNull,
    create_a, get_default_r, User, Avatar)


class OnDeleteTests(TestCase):
    def test_basics(self):
        DEFAULT = get_default_r()

        a = create_a('auto')
        a.auto.delete()
        self.assertFalse(A.objects.filter(name='auto').exists())

        a = create_a('auto_nullable')
        a.auto_nullable.delete()
        self.assertFalse(A.objects.filter(name='auto_nullable').exists())

        a = create_a('setnull')
        a.setnull.delete()
        a = A.objects.get(pk=a.pk)
        self.assertEqual(None, a.setnull)

        a = create_a('setdefault')
        a.setdefault.delete()
        a = A.objects.get(pk=a.pk)
        self.assertEqual(DEFAULT, a.setdefault)

        a = create_a('setdefault_none')
        a.setdefault_none.delete()
        a = A.objects.get(pk=a.pk)
        self.assertEqual(None, a.setdefault_none)

        a = create_a('cascade')
        a.cascade.delete()
        self.assertFalse(A.objects.filter(name='cascade').exists())

        a = create_a('cascade_nullable')
        a.cascade_nullable.delete()
        self.assertFalse(A.objects.filter(name='cascade_nullable').exists())

        a = create_a('protect')
        self.assertRaises(IntegrityError, a.protect.delete)

        # Testing DO_NOTHING is a bit harder: It would raise IntegrityError for a normal model,
        # so we connect to pre_delete and set the fk to a known value.
        replacement_r = R.objects.create()
        def check_do_nothing(sender, **kwargs):
            obj = kwargs['instance']
            obj.donothing_set.update(donothing=replacement_r)
        models.signals.pre_delete.connect(check_do_nothing)
        a = create_a('do_nothing')
        a.donothing.delete()
        a = A.objects.get(pk=a.pk)
        self.assertEqual(replacement_r, a.donothing)
        models.signals.pre_delete.disconnect(check_do_nothing)

        A.objects.all().update(protect=None, donothing=None)
        R.objects.all().delete()
        self.assertFalse(A.objects.exists())

    def test_m2m(self):
        m = M.objects.create()
        r = R.objects.create()
        MR.objects.create(m=m, r=r)
        r.delete()
        self.assertFalse(MR.objects.exists())

        r = R.objects.create()
        MR.objects.create(m=m, r=r)
        m.delete()
        self.assertFalse(MR.objects.exists())

        m = M.objects.create()
        r = R.objects.create()
        m.m2m.add(r)
        r.delete()
        through = M._meta.get_field('m2m').rel.through
        self.assertFalse(through.objects.exists())

        r = R.objects.create()
        m.m2m.add(r)
        m.delete()
        self.assertFalse(through.objects.exists())

        m = M.objects.create()
        r = R.objects.create()
        MRNull.objects.create(m=m, r=r)
        r.delete()
        self.assertFalse(not MRNull.objects.exists())
        self.assertFalse(m.m2m_through_null.exists())

    def test_bulk(self):
        from django.db.models.sql.constants import GET_ITERATOR_CHUNK_SIZE
        s = S.objects.create(r=R.objects.create())
        for i in xrange(2*GET_ITERATOR_CHUNK_SIZE):
            T.objects.create(s=s)
        #   1 (select related `T` instances)
        # + 1 (select related `U` instances)
        # + 2 (delete `T` instances in batches)
        # + 1 (delete `s`)
        self.assertNumQueries(5, s.delete)
        self.assertFalse(S.objects.exists())

    def test_instance_update(self):
        deleted = []
        related_setnull_sets = []
        def pre_delete(sender, **kwargs):
            obj = kwargs['instance']
            deleted.append(obj)
            if isinstance(obj, R):
                related_setnull_sets.append(list(a.pk for a in obj.setnull_set.all()))

        models.signals.pre_delete.connect(pre_delete)
        a = create_a('update_setnull')
        a.setnull.delete()

        a = create_a('update_cascade')
        a.cascade.delete()

        for obj in deleted:
            self.assertEqual(None, obj.pk)

        for pk_list in related_setnull_sets:
            for a in A.objects.filter(id__in=pk_list):
                self.assertEqual(None, a.setnull)

        models.signals.pre_delete.disconnect(pre_delete)

    def test_deletion_order(self):
        pre_delete_order = []
        post_delete_order = []

        def log_post_delete(sender, **kwargs):
            pre_delete_order.append((sender, kwargs['instance'].pk))

        def log_pre_delete(sender, **kwargs):
            post_delete_order.append((sender, kwargs['instance'].pk))

        models.signals.post_delete.connect(log_post_delete)
        models.signals.pre_delete.connect(log_pre_delete)

        r = R.objects.create(pk=1)
        s1 = S.objects.create(pk=1, r=r)
        s2 = S.objects.create(pk=2, r=r)
        t1 = T.objects.create(pk=1, s=s1)
        t2 = T.objects.create(pk=2, s=s2)
        r.delete()
        self.assertEqual(pre_delete_order, [(T, 2), (T, 1), (S, 2), (S, 1), (R, 1)])
        self.assertEqual(post_delete_order, [(T, 1), (T, 2), (S, 1), (S, 2), (R, 1)])

        models.signals.post_delete.disconnect(log_post_delete)
        models.signals.post_delete.disconnect(log_pre_delete)

    @skipUnlessDBFeature("can_defer_constraint_checks")
    def test_can_defer_constraint_checks(self):
        u = User.objects.create(
            avatar=Avatar.objects.create()
        )
        u = User.objects.get(pk=u.pk)
        self.assertNumQueries(2, u.delete)
