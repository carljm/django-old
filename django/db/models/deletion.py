from django.utils.datastructures import SortedDict
from django.utils.functional import wraps
from django.db import connections, transaction, IntegrityError
from django.db.models import signals, sql
from django.db.models.sql.constants import GET_ITERATOR_CHUNK_SIZE

def CASCADE(collector, field, sub_objs):
    collector.collect(sub_objs, source=field.rel.to, source_attr=field.name, nullable=field.null)
    if field.null:
        # FIXME: there should be a connection feature indicating whether nullable related fields should be nulled out before deletion
        collector.add_field_update(field, None, sub_objs)

def PROTECT(collector, field, sub_objs):
    msg = "Cannot delete some instances of model '%s' because they are referenced through a protected foreign key: '%s.%s'" % (
        field.rel.to.__name__, sub_objs[0].__class__.__name__, field.name
    )
    raise IntegrityError(msg)

def SET(value):
    def set_on_delete(collector, field, sub_objs):
        collector.add_field_update(field, value, sub_objs)
    return set_on_delete

def SET_NULL(collector, field, sub_objs):
    collector.add_field_update(field, None, sub_objs)

def SET_DEFAULT(collector, field, sub_objs):
    collector.add_field_update(field, field.get_default(), sub_objs)

def DO_NOTHING(collector, field, sub_objs):
    pass

def force_managed(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not transaction.is_managed():
            transaction.enter_transaction_management()
            forced_managed = True
        else:
            forced_managed = False
        try:                    
            func(*args, **kwargs)
            if forced_managed:
                transaction.commit()
            else:
                transaction.commit_unless_managed()
        finally:
            if forced_managed:
                transaction.leave_transaction_management()
    return decorated

class Collector(object):
    def __init__(self):
        self.data = {} # {model: [instances]}
        self.batches = {} # {model: {field: set([instances])}}
        self.field_updates = {} # {model: {(field, value): set([instances])}}        
        self.dependencies = {} # {model: set([models])}

    def add(self, objs, source=None, nullable=False):
        """
        Adds 'objs' to the collection of objects to be deleted.
        If the call is the result of a cascade, 'source' should be the model that caused it 
        and 'nullable' should be set to True, if the relation can be null.
        
        Returns a list of all objects that were not already collected.
        """
        if not objs:
            return []
        new_objs = []
        model = objs[0].__class__
        instances = self.data.setdefault(model, [])
        for obj in objs:
            if obj not in instances:
                new_objs.append(obj)
        instances.extend(new_objs)
        # Nullable relationships can be ignored -- they are nulled out before
        # deleting, and therefore do not affect the order in which objects
        # have to be deleted.
        if new_objs and source is not None and not nullable:
            self.dependencies.setdefault(source, set()).add(model)
        return new_objs
        
    def add_batch(self, model, field, objs):
        """
        Schedules a batch delete. Every instance of 'model' that is related to an instance of 'obj' through 'field' will be deleted.
        """
        self.batches.setdefault(model, {}).setdefault(field, set()).update(objs)
        
    def add_field_update(self, field, value, objs):
        """
        Schedules a field update. 'objs' must be a homogenous iterable collection of model instances (e.g. a QuerySet).
        """
        objs = list(objs)
        if not objs:
            return
        model = objs[0].__class__
        self.field_updates.setdefault(model, {}).setdefault((field, value), set()).update(objs)
        
    def collect(self, objs, source=None, nullable=False, collect_related=True, using=None, source_attr=None):
        """
        Adds 'objs' to the collection of objects to be deleted as well as all parent instances.
        'objs' must be a homogenous iterable collection of model instances (e.g. a QuerySet).
        If 'collect_related' is True, related objects will be handled by their respective on_delete handler.
        
        If the call is the result of a cascade, 'source' should be the model that caused it 
        and 'nullable' should be set to True, if the relation can be null.
        """
        
        new_objs = self.add(objs, source, nullable)
        if not new_objs:
            return
        model = new_objs[0].__class__
        
        # Recusively collect parent models, but not their related objects.
        for parent_model, ptr in model._meta.parents.iteritems():
            if ptr:
                parent_objs = [getattr(obj, ptr.name) for obj in new_objs]
                self.collect(parent_objs, source=model, source_attr=ptr.rel.related_name, collect_related=False)

        if collect_related:
            for related in model._meta.get_all_related_objects():
                field = related.field
                if field.rel.is_hidden():
                    self.add_batch(related.model, field, new_objs)
                else:
                    sub_objs = related.model._base_manager.using(using).filter(**{"%s__in" % field.name: new_objs})
                    if not sub_objs:
                        continue
                    field.rel.on_delete(self, field, sub_objs)

            # FIXME: support for generic relations should not require special handling
            for field in model._meta.many_to_many:
                if not field.rel.through:
                    # m2m-ish but with no through table? GenericRelation: cascade delete
                    for obj in new_objs:
                        self.collect(field.value_from_object(obj).all(), source=model, source_attr=field.rel.related_name, nullable=True, using=using)

    def instances_with_model(self):
        for model, instances in self.data.iteritems():
            for obj in instances:
                yield model, obj
                
    def sort(self):
        sorted_models = []
        models = self.data.keys()
        while len(sorted_models) < len(models):
            found = False
            for model in models:
                if model in sorted_models:
                    continue
                dependencies = self.dependencies.get(model)
                if not dependencies or not dependencies.difference(sorted_models):
                    sorted_models.append(model)
                    found = True
            if not found:
                return
        self.data = SortedDict([(model, self.data[model]) for model in sorted_models])
    
    @force_managed
    def delete(self, using=None):
        # sort instance collections 
        for instances in self.data.itervalues():
            instances.sort(key=lambda obj: obj.pk)

        # if possible, bring the models in an order suitable for databases that don't support transactions 
        # or cannot defer contraint checks until the end of a transaction.
        self.sort()
        
        # send pre_delete signals
        for model, obj in self.instances_with_model():
            if not model._meta.auto_created:
                signals.pre_delete.send(sender=model, instance=obj, using=using)

        # update fields
        for model, instances_for_fieldvalues in self.field_updates.iteritems():
            query = sql.UpdateQuery(model)
            for (field, value), instances in instances_for_fieldvalues.iteritems():
                query.update_batch([obj.pk for obj in instances], {field.name: value}, using)

        # reverse instance collections
        for instances in self.data.itervalues():
            instances.reverse()

        # delete batches
        for model, batches in self.batches.iteritems():
            query = sql.DeleteQuery(model)
            for field, instances in batches.iteritems():
                query.delete_batch([obj.pk for obj in instances], using, field)

        # delete instances
        for model, instances in self.data.iteritems():
            query = sql.DeleteQuery(model)
            pk_list = [obj.pk for obj in instances]
            #query.delete_generic_relation_hack(pk_list, using)
            query.delete_batch(pk_list, using)
        
        # send post_delete signals
        for model, obj in self.instances_with_model():
            if not model._meta.auto_created:
                signals.post_delete.send(sender=model, instance=obj, using=using)
        
        # update collected instances
        for model, instances_for_fieldvalues in self.field_updates.iteritems():
            for (field, value), instances in instances_for_fieldvalues.iteritems():
                for obj in instances:
                    setattr(obj, field.attname, value)
        for model, instances in self.data.iteritems():
            for instance in instances:
                setattr(instance, model._meta.pk.attname, None)
