from django.test import TestCase
from django.db import models, IntegrityError

class R(models.Model):
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return "%s" % self.pk

get_default_r = lambda: R.objects.get_or_create(is_default=True)[0]
    
class S(models.Model):
    r = models.ForeignKey(R)
    
class T(models.Model):
    s = models.ForeignKey(S)

class U(models.Model):
    t = models.ForeignKey(T)


class A(models.Model):
    name = models.CharField(max_length=10)    

    auto = models.ForeignKey(R, related_name="auto_set")
    auto_nullable = models.ForeignKey(R, null=True, related_name='auto_nullable_set')
    setnull = models.ForeignKey(R, on_delete=models.SET_NULL, null=True, related_name='setnull_set')
    setdefault = models.ForeignKey(R, on_delete=models.SET_DEFAULT, default=get_default_r, related_name='setdefault_set')
    setdefault_none = models.ForeignKey(R, on_delete=models.SET_DEFAULT, default=None, null=True, related_name='setnull_nullable_set')
    cascade = models.ForeignKey(R, on_delete=models.CASCADE, related_name='cascade_set')
    cascade_nullable = models.ForeignKey(R, on_delete=models.CASCADE, null=True, related_name='cascade_nullable_set')
    protect = models.ForeignKey(R, on_delete=models.PROTECT, null=True)
    donothing = models.ForeignKey(R, on_delete=models.DO_NOTHING, null=True, related_name='donothing_set')
    
def create_a(name):
    a = A(name=name)
    for name in ('auto', 'auto_nullable', 'setnull', 'setdefault', 'setdefault_none', 'cascade', 'cascade_nullable', 'protect', 'donothing'):
        r = R.objects.create()
        setattr(a, name, r)
    a.save()
    return a
    
class M(models.Model):
    m2m = models.ManyToManyField(R, related_name="m_set")    
    m2m_through = models.ManyToManyField(R, through="MR", related_name="m_through_set")
    m2m_through_null = models.ManyToManyField(R, through="MRNull", related_name="m_through_null_set")
    
class MR(models.Model):
    m = models.ForeignKey(M)
    r = models.ForeignKey(R)

class MRNull(models.Model):
    m = models.ForeignKey(M)
    r = models.ForeignKey(R, null=True, on_delete=models.SET_NULL)

class OnDeleteTests(TestCase):
    def test_basics(self):
        DEFAULT = get_default_r()
        
        a = create_a('auto')
        a.auto.delete()
        self.failIf(A.objects.filter(name='auto').exists())
        
        a = create_a('auto_nullable')
        a.auto_nullable.delete()
        self.failIf(A.objects.filter(name='auto_nullable').exists())
        
        a = create_a('setnull')
        a.setnull.delete()
        a = A.objects.get(pk=a.pk)
        self.failUnlessEqual(None, a.setnull)
        
        a = create_a('setdefault')
        a.setdefault.delete()
        a = A.objects.get(pk=a.pk)
        self.failUnlessEqual(DEFAULT, a.setdefault)
        
        a = create_a('setdefault_none')
        a.setdefault_none.delete()
        a = A.objects.get(pk=a.pk)
        self.failUnlessEqual(None, a.setdefault_none)
        
        a = create_a('cascade')
        a.cascade.delete()
        self.failIf(A.objects.filter(name='cascade').exists())
        
        a = create_a('cascade_nullable')
        a.cascade_nullable.delete()
        self.failIf(A.objects.filter(name='cascade_nullable').exists())
        
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
        self.failUnlessEqual(replacement_r, a.donothing)
        models.signals.pre_delete.disconnect(check_do_nothing)        
        
        A.objects.all().update(protect=None, donothing=None)
        R.objects.all().delete()
        self.failIf(A.objects.exists())
        
    def test_m2m(self):
        m = M.objects.create()
        r = R.objects.create()
        MR.objects.create(m=m, r=r)
        r.delete()
        self.failIf(MR.objects.exists())
        
        r = R.objects.create()
        MR.objects.create(m=m, r=r)
        m.delete()
        self.failIf(MR.objects.exists())
        
        m = M.objects.create()
        r = R.objects.create()
        m.m2m.add(r)
        r.delete()
        through = M._meta.get_field('m2m').rel.through
        self.failIf(through.objects.exists())
        
        r = R.objects.create()
        m.m2m.add(r)
        m.delete()
        self.failIf(through.objects.exists())
        
        m = M.objects.create()
        r = R.objects.create()
        MRNull.objects.create(m=m, r=r)
        r.delete()
        self.failIf(not MRNull.objects.exists())
        self.failIf(m.m2m_through_null.exists())
        
    
    def assert_num_queries(self, num, func, *args, **kwargs):
        # FIXME: replace with the new builtin method
        from django.conf import settings
        from django.db import connection
        old_debug = settings.DEBUG
        settings.DEBUG = True
        query_count = len(connection.queries)
        func(*args, **kwargs)
        self.failUnlessEqual(num, len(connection.queries) - query_count)
        connection.queries = connection.queries[:query_count]
        settings.DEBUG = old_debug
    
    def test_bulk(self):
        from django.db.models.sql.constants import GET_ITERATOR_CHUNK_SIZE
        s = S.objects.create(r=R.objects.create())
        for i in xrange(2*GET_ITERATOR_CHUNK_SIZE):
            T.objects.create(s=s)
        #   1 (select related `T` instances)
        # + 1 (select related `U` instances)
        # + 2 (delete `T` instances in batches)
        # + 1 (delete `s`)
        self.assert_num_queries(5, s.delete)
        self.failIf(S.objects.exists())
        
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
            self.failUnlessEqual(None, obj.pk)
            
        for pk_list in related_setnull_sets:
            for a in A.objects.filter(id__in=pk_list):
                self.failUnlessEqual(None, a.setnull)
        
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
        self.failUnlessEqual(pre_delete_order, [(T, 2), (T, 1), (S, 2), (S, 1), (R, 1)])
        self.failUnlessEqual(post_delete_order, [(T, 1), (T, 2), (S, 1), (S, 2), (R, 1)])
        
        models.signals.post_delete.disconnect(log_post_delete)
        models.signals.post_delete.disconnect(log_pre_delete)
        
