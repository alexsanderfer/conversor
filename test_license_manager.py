"""
Testes da logica de licenca (stdlib unittest, sem dependencias).

Correr:  python -m unittest test_license_manager -v

Estes testes usam um segredo PROPRIO, diferente do segredo de
producao, para nao o expor em logs de CI.
"""

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import license_manager as lm

TEST_SECRET = "segredo-de-teste-apenas-para-estes-testes"


def make_payload(**overrides) -> dict:
    payload = {
        "licensee": "Loja de Teste",
        "issued": "2020-01-01T00:00:00Z",
        "expires": "2035-01-01T00:00:00Z",
        "machine_id": lm.compute_machine_fingerprint(),
        "nonce": uuid.uuid4().hex,
    }
    payload.update(overrides)
    return payload


def write_license(dirpath: Path, payload: dict) -> Path:
    path = dirpath / "teste.lic"
    path.write_text(lm.sign_license(payload, TEST_SECRET), encoding="utf-8")
    return path


class TestCanonicalizacao(unittest.TestCase):
    def test_remove_signature(self):
        data = {"a": 1, "signature": "xyz"}
        self.assertNotIn(b"signature", lm.canonicalize_license_payload(data))

    def test_ordem_das_chaves_nao_altera_bytes(self):
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        self.assertEqual(
            lm.canonicalize_license_payload(a),
            lm.canonicalize_license_payload(b),
        )

    def test_unicode_preservado(self):
        data = {"licensee": "Loja São & Filhos"}
        self.assertIn(
            "São".encode("utf-8"), lm.canonicalize_license_payload(data)
        )

    def test_assinar_e_verificar(self):
        payload = make_payload()
        signed = json.loads(lm.sign_license(payload, TEST_SECRET))
        self.assertTrue(lm._verify_signature(signed, TEST_SECRET))

    def test_assinatura_invalida_se_payload_alterado(self):
        signed = json.loads(lm.sign_license(make_payload(), TEST_SECRET))
        signed["licensee"] = "Outra Loja"
        self.assertFalse(lm._verify_signature(signed, TEST_SECRET))

    def test_segredo_diferente_rejeita(self):
        signed = json.loads(lm.sign_license(make_payload(), TEST_SECRET))
        self.assertFalse(lm._verify_signature(signed, "outro-segredo"))


class TestVerificacao(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.lic = self.dir / "teste.lic"

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, path=None):
        return lm.check_license(
            path or self.lic, state_dir=self.dir, secret=TEST_SECRET
        )

    def test_licenca_valida(self):
        write_license(self.dir, make_payload())
        ok, reason = self.check()
        self.assertTrue(ok, reason)

    def test_ficheiro_inexistente(self):
        ok, reason = self.check(self.dir / "nao_existe.lic")
        self.assertFalse(ok)
        self.assertIn("não encontrado", reason)

    def test_json_invalido(self):
        self.lic.write_text("{isto nao e json", encoding="utf-8")
        ok, reason = self.check()
        self.assertFalse(ok)

    def test_assinatura_adulterada(self):
        write_license(self.dir, make_payload())
        data = json.loads(self.lic.read_text(encoding="utf-8"))
        data["expires"] = "2040-01-01T00:00:00Z"  # esticar a validade
        self.lic.write_text(json.dumps(data), encoding="utf-8")
        ok, reason = self.check()
        self.assertFalse(ok)
        self.assertIn("alterado", reason)

    def test_licenca_de_outra_maquina(self):
        write_license(self.dir, make_payload(machine_id="maquina-que-nao-e-esta"))
        ok, reason = self.check()
        self.assertFalse(ok)
        self.assertIn("este computador", reason)

    def test_licenca_expirada(self):
        write_license(
            self.dir,
            make_payload(issued="2020-01-01T00:00:00Z", expires="2021-01-01T00:00:00Z"),
        )
        ok, reason = self.check()
        self.assertFalse(ok)
        self.assertIn("expirada", reason)

    def test_licenca_ainda_nao_valida(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        later = future + timedelta(days=365)
        write_license(
            self.dir,
            make_payload(
                issued=future.isoformat().replace("+00:00", "Z"),
                expires=later.isoformat().replace("+00:00", "Z"),
            ),
        )
        ok, reason = self.check()
        self.assertFalse(ok)
        self.assertIn("ainda não entra em vigor", reason)

    def test_datas_malformadas(self):
        write_license(self.dir, make_payload(expires="nao-e-uma-data"))
        ok, reason = self.check()
        self.assertFalse(ok)
        self.assertIn("datas inválidas", reason)


class TestEstadoERelogio(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_estado_gravado_e_lido(self):
        lm.save_license_state(self.dir, {"chave": "valor"})
        self.assertEqual(lm.load_license_state(self.dir), {"chave": "valor"})

    def test_estado_inexistente_vazio(self):
        self.assertEqual(lm.load_license_state(self.dir / "sub"), {})

    def test_relogio_recusado(self):
        agora = datetime.now(timezone.utc)
        lm.save_license_state(
            self.dir, {"max_seen_time": agora.isoformat().replace("+00:00", "Z")}
        )
        lic = write_license(self.dir, make_payload())
        # simula o utilizador ter recuado o relogio: gravamos um
        # max_seen_time no futuro e pedimos a verificacao "agora"
        lm.save_license_state(
            self.dir,
            {
                "max_seen_time": (agora + timedelta(hours=2))
                .isoformat()
                .replace("+00:00", "Z")
            },
        )
        ok, reason = lm.check_license(
            lic, state_dir=self.dir, secret=TEST_SECRET
        )
        self.assertFalse(ok)
        self.assertIn("recuado", reason)

    def test_tolerancia_de_dois_minutos(self):
        """Um ajuste NTP de ~1 min nao deve bloquear."""
        agora = datetime.now(timezone.utc)
        lm.save_license_state(
            self.dir,
            {
                "max_seen_time": (agora - timedelta(seconds=60))
                .isoformat()
                .replace("+00:00", "Z")
            },
        )
        lic = write_license(self.dir, make_payload())
        ok, reason = lm.check_license(lic, state_dir=self.dir, secret=TEST_SECRET)
        self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)