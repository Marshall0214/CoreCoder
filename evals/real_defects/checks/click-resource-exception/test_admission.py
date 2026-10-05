import unittest

import click


class Resource:
    def __init__(self, suppress=False):
        self.events = []
        self.suppress = suppress

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.events.append((kind, value, traceback))
        return self.suppress


class Target(unittest.TestCase):
    def test_resource_receives_exception(self):
        resource = Resource()
        error = ValueError('admission-example')
        with self.assertRaises(ValueError), click.Context(click.Command('example')) as ctx:
            ctx.with_resource(resource)
            raise error
        self.assertIs(resource.events[0][0], ValueError)
        self.assertIs(resource.events[0][1], error)
        self.assertIsNotNone(resource.events[0][2])

    def test_resource_can_suppress_exception(self):
        resource = Resource(suppress=True)
        escaped = False
        try:
            with click.Context(click.Command('example')) as ctx:
                ctx.with_resource(resource)
                raise ValueError('handled-by-resource')
        except ValueError:
            escaped = True
        self.assertFalse(escaped)
        self.assertIs(resource.events[0][0], ValueError)


class Controls(unittest.TestCase):
    def test_normal_exit_has_no_exception(self):
        resource = Resource()
        with click.Context(click.Command('example')) as ctx:
            ctx.with_resource(resource)
        self.assertEqual(resource.events, [(None, None, None)])
