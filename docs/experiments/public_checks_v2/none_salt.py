"""Public salt relations plus original-API preservation checks; hand-authored v2."""

import unittest
from functools import partial

from itsdangerous import BadSignature, Serializer, Signer

KEY = 'public-development-key'
VALUE = {'label': 'public-example', 'count': 2}


class PublicContract(unittest.TestCase):
    def expected_success(self, operation):
        try:
            return operation()
        except (TypeError, ValueError, BadSignature) as exc:
            self.fail(f'Public relation expects successful signing/loading; got {type(exc).__name__}: {exc}')

    def test_signer_none_uses_signer_default(self):
        actual = self.expected_success(lambda: Signer(KEY, salt=None).sign(b'public-message'))
        self.assertEqual(actual, Signer(KEY).sign(b'public-message'))

    def test_serializer_none_matches_explicit_signer(self):
        serializer = Serializer(KEY, salt=None)
        payload = serializer.dump_payload(VALUE)
        payload = payload.encode('utf-8') if isinstance(payload, str) else payload
        actual = self.expected_success(lambda: serializer.dumps(VALUE))
        actual = actual.encode('utf-8') if isinstance(actual, str) else actual
        self.assertEqual(actual, Signer(KEY).sign(payload))

    def test_serializer_none_round_trip(self):
        serializer = Serializer(KEY, salt=None)
        token = self.expected_success(lambda: serializer.dumps(VALUE))
        self.assertEqual(self.expected_success(lambda: serializer.loads(token)), VALUE)

    def test_explicit_string_and_bytes_salts(self):
        for factory in (Signer, Serializer):
            with self.subTest(factory=factory.__name__):
                left, right = factory(KEY, salt='public-salt'), factory(KEY, salt=b'public-salt')
                if factory is Signer:
                    self.assertEqual(left.sign(b'public-message'), right.sign(b'public-message'))
                else:
                    self.assertEqual(left.dumps(VALUE), right.dumps(VALUE))
                    self.assertEqual(self.expected_success(partial(right.loads, left.dumps(VALUE))), VALUE)

    def test_omitted_serializer_salt_preserved(self):
        # This literal is from the original public constructor signature, not a reference patch.
        self.assertEqual(Serializer(KEY).dumps(VALUE), Serializer(KEY, salt=b'itsdangerous').dumps(VALUE))

    def test_wrong_salt_rejected(self):
        token = Serializer(KEY, salt='first-public-salt').dumps(VALUE)
        with self.assertRaises(BadSignature):
            Serializer(KEY, salt='second-public-salt').loads(token)

    def test_tampered_value_rejected(self):
        serializer = Serializer(KEY)
        token = serializer.dumps(VALUE)
        suffix = '-tampered' if isinstance(token, str) else b'-tampered'
        with self.assertRaises(BadSignature):
            serializer.loads(token + suffix)

    def expected_token(self, serializer, salt):
        payload = serializer.dump_payload(VALUE)
        payload = payload.encode('utf-8') if isinstance(payload, str) else payload
        expected = Signer(KEY).sign(payload) if salt is None else Signer(KEY, salt=salt).sign(payload)
        return expected.decode('utf-8') if serializer.is_text_serializer else expected

    def test_omitted_default_matches_independent_signer(self):
        serializer = Serializer(KEY)
        self.assertEqual(serializer.dumps(VALUE), self.expected_token(serializer, b'itsdangerous'))

    def test_constructor_none_distinct_from_omission(self):
        actual = self.expected_success(lambda: Serializer(KEY, salt=None).dumps(VALUE))
        self.assertNotEqual(actual, Serializer(KEY).dumps(VALUE))

    def test_explicit_constructor_salt_exact_signature(self):
        for salt in ('public-explicit', b'public-explicit', b''):
            with self.subTest(salt=salt):
                serializer = Serializer(KEY, salt=salt)
                self.assertEqual(serializer.dumps(VALUE), self.expected_token(serializer, salt))

    def test_method_salt_override_matrix(self):
        # Existing API: method None/omission uses the instance salt; explicit values override it.
        constructors = [({}, b'itsdangerous'), ({'salt': None}, None),
                        ({'salt': b'instance-salt'}, b'instance-salt'), ({'salt': b''}, b'')]
        for kwargs, instance_salt in constructors:
            for method_kwargs in ({}, {'salt': None}, {'salt': b'override-salt'},
                                  {'salt': 'override-salt'}, {'salt': b''}):
                with self.subTest(constructor=kwargs, method=method_kwargs):
                    serializer = Serializer(KEY, **kwargs)
                    effective = method_kwargs.get('salt')
                    effective = instance_salt if effective is None else effective
                    token = self.expected_success(partial(serializer.dumps, VALUE, **method_kwargs))
                    self.assertEqual(token, self.expected_token(serializer, effective))
                    self.assertEqual(self.expected_success(partial(serializer.loads, token, **method_kwargs)), VALUE)
                    if method_kwargs.get('salt') is not None:
                        other = Serializer(KEY, salt=b'unrelated-instance')
                        self.assertEqual(self.expected_success(partial(other.loads, token, **method_kwargs)), VALUE)
