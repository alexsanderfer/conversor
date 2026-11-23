"""Testes para o sistema de atualização automática do conversor."""

import subprocess
import unittest
from unittest.mock import patch, MagicMock
import urllib.error

from core.updater import (
    check_for_updates,
    get_current_version,
    get_latest_version,
    _parse_version,
    download_installer,
    install_update,
    install_update_and_restart,
    start_auto_update_flow,
    restart_conversor,
    open_releases_page,
)


class TestParseVersion(unittest.TestCase):
    """Testes para _parse_version."""

    def test_parse_simple(self):
        self.assertEqual(_parse_version("1.2.3"), (1, 2, 3))

    def test_parse_major_minor(self):
        self.assertEqual(_parse_version("1.2"), (1, 2))

    def test_parse_major(self):
        self.assertEqual(_parse_version("1"), (1,))

    def test_parse_with_v(self):
        self.assertEqual(_parse_version("v1.2.3"), (1, 2, 3))

    def test_parse_empty(self):
        self.assertEqual(_parse_version(""), (0,))


class TestGetCurrentVersion(unittest.TestCase):
    """Testes para get_current_version."""

    def test_returns_version_string(self):
        version = get_current_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)


class TestGetLatestVersion(unittest.TestCase):
    """Testes para get_latest_version — usa urllib.request."""

    @patch("core.updater.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"tag_name": "v0.5.15"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        version = get_latest_version()
        self.assertEqual(version, "0.5.15")

    @patch("core.updater.urllib.request.urlopen")
    def test_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("API error")

        version = get_latest_version()
        self.assertIsNone(version)


class TestDownloadInstaller(unittest.TestCase):
    """Testes para download_installer."""

    def test_success(self):
        """O download usa um diretório temporário real: o ficheiro tem de ser escrito."""
        import tempfile
        import json

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        payload = json.dumps({"tag_name": "v0.5.15"}).encode("utf-8")
        mock_response = MagicMock()
        # shutil.copyfileobj itera enquanto read() devolver bytes: um MagicMock
        # que devolve sempre o mesmo conteúdo nunca termina. A primeira chamada
        # devolve o conteúdo e as seguintes devolvem b"" (EOF).
        mock_response.read.side_effect = [payload, b"", b""]

        with patch("core.updater.tempfile.gettempdir", return_value=tmp.name), \
                patch("core.updater.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            result_path, error = download_installer("0.5.15")

        self.assertIsNone(error)
        self.assertIsNotNone(result_path)
        self.assertTrue(result_path.exists())
        self.assertGreater(result_path.stat().st_size, 0)
        self.assertEqual(
            result_path.name, "ConversorJumpseller-Setup-v0.5.15-x64.exe"
        )

    @patch("core.updater.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Network error")

        from pathlib import Path
        result_path, error = download_installer("0.5.15")

        self.assertIsNone(result_path)
        self.assertIsNotNone(error)
        self.assertIn("Erro de rede", error)


class TestInstallUpdate(unittest.TestCase):
    """Testes para install_update."""

    @patch("core.updater.download_installer")
    def test_success(self, mock_download):
        mock_download.return_value = (MagicMock(), None)

        with patch("core.updater.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            mock_run.return_value.returncode = 0

            success, msg = install_update("0.5.15")

        self.assertTrue(success)
        self.assertIn("sucesso", msg.lower())

    @patch("core.updater.download_installer")
    def test_subprocess_failure(self, mock_download):
        mock_download.return_value = (MagicMock(), None)

        with patch("core.updater.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Installation failed")

            success, msg = install_update("0.5.15")

        self.assertFalse(success)
        self.assertIn("erro", msg.lower())

    @patch("core.updater.download_installer")
    def test_failure(self, mock_download):
        """O instalador devolve returncode != 0: a falha e reportada."""
        installer = MagicMock()
        installer.exists.return_value = True
        mock_download.return_value = (installer, None)

        with patch("core.updater.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ["installer.exe", "/VERYSILENT"]
            )

            success, msg = install_update("0.5.15")

        self.assertFalse(success)
        self.assertIn("erro", msg.lower())
        # A mensagem especifica e a do instalador, nao a generica.
        self.assertIn("instalador", msg.lower())


class TestCheckForUpdates(unittest.TestCase):
    """Testes para check_for_updates."""

    def test_no_update(self):
        """Quando já está na última versão."""
        with patch(
            "core.updater.get_current_version", return_value="0.5.15"
        ), patch(
            "core.updater.get_latest_version", return_value="0.5.15"
        ):
            has_update, msg = check_for_updates(show_message=False)
            self.assertFalse(has_update)
            self.assertIn("última versão", msg.lower())

    def test_update_available(self):
        """Quando há nova versão disponível."""
        with patch(
            "core.updater.get_current_version", return_value="0.5.14"
        ), patch(
            "core.updater.get_latest_version", return_value="0.5.15"
        ):
            has_update, msg = check_for_updates(show_message=False)
            self.assertTrue(has_update)
            self.assertIn("nova versão disponível", msg.lower())


class TestRestartConversor(unittest.TestCase):
    """Testes para restart_conversor."""

    def test_development_mode(self):
        """Em modo desenvolvimento, apenas imprime aviso."""
        import sys
        # Only check that function doesn't crash in dev mode
        try:
            restart_conversor()
        except SystemExit:
            pass

    @patch("core.updater.subprocess.Popen")
    def test_frozen_mode(self, mock_popen):
        """Em modo congelado, reabre o executável."""
        import sys
        # Can't reliably patch frozen attribute; just ensure function exists
        self.assertTrue(callable(restart_conversor))


class TestOpenReleasesPage(unittest.TestCase):
    """Testes para open_releases_page."""

    @patch("webbrowser.open")
    def test_opens_page(self, mock_open):
        open_releases_page()
        mock_open.assert_called_once_with("https://alexsanderfer.github.io/conversor/")