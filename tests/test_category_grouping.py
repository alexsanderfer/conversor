"""Testes do motor de agrupamento automatico de categorias."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

from core.category_grouping import suggest_groupings

INFORMATICA = "Inform" + "á" + "tica"
MOVEIS = "M" + "ó" + "veis"
CASA_COZINHA = "Casa e Cozinha"
BELEZA = "Beleza e Cuidados"


class TestSuggestGroupings(unittest.TestCase):
    def test_agrupa_por_palavra_chave(self):
        categorias = [
            INFORMATICA + " > Computadores",
            INFORMATICA + " > Monitores",
            "Ferramentas > Chaves",
            "Ferramentas > Martelos",
        ]

        resultado = suggest_groupings(categorias)

        self.assertEqual(
            resultado,
            {
                "Ferramentas": ["Ferramentas > Chaves", "Ferramentas > Martelos"],
                INFORMATICA: [
                    INFORMATICA + " > Computadores",
                    INFORMATICA + " > Monitores",
                ],
            },
        )

    def test_ignora_categorias_sem_correspondencia(self):
        # "Categoria Misteriosa" nao case com nenhuma keyword e deve ser
        # ignorada; as entradas vazias tambem.
        categorias = [
            "Informatica > Computadores",
            "Categoria Misteriosa",
            "",
            "   ",
        ]

        resultado = suggest_groupings(categorias)

        self.assertEqual(
            resultado, {INFORMATICA: ["Informatica > Computadores"]}
        )

    def test_lista_vazia_devolve_dicionario_vazio(self):
        self.assertEqual(suggest_groupings([]), {})

    def test_uma_categoria_so_pertence_a_uma_area(self):
        # "cadeira" (Moveis) e "cadeira gamer" (Informatica) casam:
        # a area com maior pontuacao fica com a categoria.
        resultado = suggest_groupings(["Cadeira Gamer"])

        self.assertEqual(resultado, {INFORMATICA: ["Cadeira Gamer"]})
        self.assertNotIn(MOVEIS, resultado)

    def test_pontuacao_e_soma_do_comprimento_das_palavras_chave(self):
        # Informatica soma 9 (ssd, ram, hub); Beleza soma 11 (desodorante).
        # Ganha a maior soma, mesmo com menos keywords.
        resultado = suggest_groupings(["SSD RAM HUB Desodorante"])

        self.assertEqual(resultado, {BELEZA: ["SSD RAM HUB Desodorante"]})

    def test_empate_para_a_regra_que_aparece_primeiro(self):
        # "chave" (Ferramentas) e "garfo" (Casa e Cozinha) tem o mesmo
        # comprimento; Casa e Cozinha aparece primeiro em DEFAULT_RULES.
        resultado = suggest_groupings(["Chave Garfo"])

        self.assertEqual(resultado, {CASA_COZINHA: ["Chave Garfo"]})
        self.assertNotIn("Ferramentas", resultado)

    def test_devolve_ordem_alfabetica(self):
        categorias = [
            "Ilumina" + "ç" + "ã" + "o > Lumin" + "á" + "rias",
            "Desporto > Bolas",
            "Brinquedos > Bonecas",
            "Desporto > Raquetes",
        ]

        resultado = suggest_groupings(categorias)

        self.assertEqual(
            list(resultado.keys()),
            ["Brinquedos", "Desporto", "Ilumina" + "ç" + "ã" + "o"],
        )
        self.assertEqual(
            resultado["Desporto"], ["Desporto > Bolas", "Desporto > Raquetes"]
        )

    def test_ignora_duplicados_na_entrada(self):
        entrada = INFORMATICA + " > Computadores"
        resultado = suggest_groupings([entrada, entrada])

        self.assertEqual(resultado, {INFORMATICA: [entrada]})


if __name__ == "__main__":
    unittest.main()
