import unittest

from core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, TRANSLATABLE_STRINGS, translate


class TestI18n(unittest.TestCase):
    def test_supported_languages_have_complete_catalog(self):
        for language in SUPPORTED_LANGUAGES:
            with self.subTest(language=language):
                missing = [
                    text for text in TRANSLATABLE_STRINGS
                    if not translate(text, language).strip()
                ]
                self.assertEqual(missing, [])

    def test_english_catalog_translates_core_interface(self):
        self.assertEqual(translate("Comprar Licença", "en"), "Buy License")
        self.assertEqual(translate("Escolher arquivo…", "en"), "Choose file…")
        self.assertEqual(translate("Configuração de Preços (por perfil)", "en"), "Price Settings (per profile)")

    def test_brazilian_catalog_translates_core_interface(self):
        self.assertEqual(translate("Novo Ficheiro", "pt-BR"), "Novo Arquivo")
        self.assertEqual(translate("Pasta de destino:", "pt-BR"), "Pasta de destino:")
        self.assertEqual(translate("Escolher ficheiro…", "pt-BR"), "Escolher arquivo…")

    def test_unknown_text_keeps_source_text(self):
        self.assertEqual(translate("Texto fora do catálogo", "en"), "Texto fora do catálogo")
        self.assertEqual(DEFAULT_LANGUAGE, "pt-PT")


if __name__ == "__main__":
    unittest.main()
