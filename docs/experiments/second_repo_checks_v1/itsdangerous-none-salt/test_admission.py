import unittest

from itsdangerous import BadSignature, Serializer, Signer


class Target(unittest.TestCase):
    def test_signer_none_uses_default(self):
        try:
            actual = Signer('secret', salt=None).sign(b'value')
        except TypeError as exc:
            self.fail(f'salt=None must sign successfully: {type(exc).__name__}')
        self.assertEqual(actual, Signer('secret').sign(b'value'))

    def test_serializer_none_roundtrip_and_compatibility(self):
        serializer = Serializer('secret', salt=None)
        try:
            token = serializer.dumps({'answer': 42})
            recovered = serializer.loads(token)
        except TypeError as exc:
            self.fail(f'salt=None must round-trip: {type(exc).__name__}')
        self.assertEqual(recovered, {'answer': 42})
        self.assertEqual(token, Serializer('secret', salt=b'itsdangerous.Signer').dumps({'answer': 42}))
        self.assertNotEqual(token, Serializer('secret').dumps({'answer': 42}))


class Controls(unittest.TestCase):
    def test_explicit_salts_and_default(self):
        value = [1, 'two']
        for salt in ('custom', b'custom', b''):
            serializer = Serializer('secret', salt=salt)
            self.assertEqual(serializer.loads(serializer.dumps(value)), value)
        self.assertEqual(Serializer('secret').dumps(value), Serializer('secret', salt=b'itsdangerous').dumps(value))
        self.assertEqual(Signer('secret', salt='custom').sign(b'value'), Signer('secret', salt=b'custom').sign(b'value'))

    def test_wrong_salt_and_tamper(self):
        token = Serializer('secret', salt='one').dumps({'value': 1})
        with self.assertRaises(BadSignature):
            Serializer('secret', salt='two').loads(token)
        with self.assertRaises(BadSignature):
            Serializer('secret', salt='one').loads('changed' + token)
