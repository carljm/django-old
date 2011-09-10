from django.conf import settings
from django.template import VariableNode, Context, TemplateSyntaxError
from django.template.loader import get_template_from_string
from django.utils.unittest import TestCase
from django.test.utils import override_settings

class NodelistTest(TestCase):

    def test_for(self):
        source = '{% for i in 1 %}{{ a }}{% endfor %}'
        template = get_template_from_string(source)
        vars = template.nodelist.get_nodes_by_type(VariableNode)
        self.assertEqual(len(vars), 1)

    def test_if(self):
        source = '{% if x %}{{ a }}{% endif %}'
        template = get_template_from_string(source)
        vars = template.nodelist.get_nodes_by_type(VariableNode)
        self.assertEqual(len(vars), 1)

    def test_ifequal(self):
        source = '{% ifequal x y %}{{ a }}{% endifequal %}'
        template = get_template_from_string(source)
        vars = template.nodelist.get_nodes_by_type(VariableNode)
        self.assertEqual(len(vars), 1)

    def test_ifchanged(self):
        source = '{% ifchanged x %}{{ a }}{% endifchanged %}'
        template = get_template_from_string(source)
        vars = template.nodelist.get_nodes_by_type(VariableNode)
        self.assertEqual(len(vars), 1)


class ErrorIndexTest(TestCase):
    """
    Checks whether index of error is calculated correctly in
    template debugger in for loops. Refs ticket #5831
    """
    @override_settings(DEBUG=True, TEMPLATE_DEBUG = True)
    def test_correct_exception_index(self):
        '''
        Looks at an exception page and confirms that the information about the source of an error that occurs during template rendering appears in the appropriate location.
        '''
        tests = [ #In each case, we have template contents and the lines at which we expect the template error information to occur.
            ('{% load bad_tag %}{% for i in range %}{% badsimpletag %}{% endfor %}', (18, 38)),
            ('{% load bad_tag %}{% for i in range %}{% for j in range %}{% badsimpletag %}{% endfor %}{% endfor %}', (18, 38)),
            ('{% load bad_tag %}{% for i in range %}{% badsimpletag %}{% for j in range %}Hello{% endfor %}{% endfor %}', (18, 38)),
            ('{% load bad_tag %}{% for i in range %}{% for j in five %}{% badsimpletag %}{% endfor %}{% endfor %}', (18, 38)),
            ('{% load bad_tag %}{% for j in five %}{% badsimpletag %}{% endfor %}', (18, 37)),
        ]
        context = Context({
            'range': range(5),
            'five': 5,
        })
        for source, expected_error_source_index in tests:
            template = get_template_from_string(source)
            try:
                template.render(context)
            except (RuntimeError, TypeError), e:
                error_source_index = e.django_template_source[1]
                self.assertEqual(error_source_index,
                                 expected_error_source_index)
