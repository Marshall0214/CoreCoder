"""Relational checks from public None/default/explicit salt and tamper requirements."""

import unittest

from itsdangerous import BadSignature, Serializer, Signer

KEY = 'public-development-key'
VALUE = {'label': 'public-example', 'count': 2}


class PublicContract(unittest.TestCase):
    def accepting_none(self, operation):
        try:
            return operation()
        except (TypeError, ValueError) as exc:
            self.fail(f'Public requirement says salt=None must work; got {type(exc).__name__}: {exc}')

    def test_signer_none_uses_signer_default(self):
        actual = self.accepting_none(lambda: Signer(KEY, salt=None).sign(b'public-message'))
        self.assertEqual(actual, Signer(KEY).sign(b'public-message'))

    def test_serializer_none_matches_explicit_signer(self):
        serializer = Serializer(KEY, salt=None)
        payload = serializer.dump_payload(VALUE)
        payload = payload.encode('utf-8') if isinstance(payload, str) else payload
        actual = self.accepting_none(lambda: serializer.dumps(VALUE))
        actual = actual.encode('utf-8') if isinstance(actual, str) else actual
        self.assertEqual(actual, Signer(KEY).sign(payload))

    def test_serializer_none_round_trip(self):
        serializer = Serializer(KEY, salt=None)
        token = self.accepting_none(lambda: serializer.dumps(VALUE))
        self.assertEqual(self.accepting_none(lambda: serializer.loads(token)), VALUE)

    def test_explicit_string_and_bytes_salts(self):
        for factory in (Signer, Serializer):
            with self.subTest(factory=factory.__name__):
                left, right = factory(KEY, salt='public-salt'), factory(KEY, salt=b'public-salt')
                if factory is Signer:
                    self.assertEqual(left.sign(b'public-message'), right.sign(b'public-message'))
                else:
                    self.assertEqual(left.dumps(VALUE), right.dumps(VALUE))
                    self.assertEqual(right.loads(left.dumps(VALUE)), VALUE)

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
