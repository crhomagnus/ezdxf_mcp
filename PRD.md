# PRD — `ezdxf_mcp` v3.0

**Servidor MCP para estruturação, validação e formatação de arquivos DXF**

**Versão:** 3.0 — cobertura ampla da API, foco no formato
**Data:** 2026-07-24
**Owner:** Márcio Silva Moreira
**Executor:** Claude Code
**Repositório alvo:** `~/projects/ezdxf_mcp/`
**Base:** ezdxf 1.4.4 (MIT, Manfred Moitzi)

> **Substitui v1.0 e v2.0.**
> O v1 leu 7 páginas e escolheu um recorte sem declarar. O v2 leu tudo, mas girou o eixo para produção CNC — nesting, compensação de ferramenta, ordem de corte. **O v3 recentra no que foi pedido desde o início: a estrutura e a formatação do tipo de arquivo.** Produção passa a ser aplicação derivada (seção 16), não o núcleo.

---

## 0. Como o Claude Code deve usar este documento

1. Leia o PRD inteiro antes da primeira linha de código.
2. Implemente na ordem dos **Marcos (seção 13)**. Não pule marco.
3. **`[MEDIDO]`** = verificado empiricamente nesta base, log no documento. É fato.
4. **`[MEDIR]`** = desconhecido. Determine por teste, nunca assuma.
5. **Proibido declarar função operante sem log de runtime.** Proibido fallback silencioso com valor inventado.
6. A seção 2 é o mapa de cobertura dos 79 módulos. Nada foi omitido por descuido.

### 0.1 Base documental

```
290 arquivos .rst  ·  42.487 linhas  ·  79 módulos  ·  411 funções  ·  388 classes
```

Fonte: `docs/source/` de `mozman/ezdxf` na tag `v1.4.4`, lido integralmente — **incluindo a seção `dxfinternals/`**, que é a espinha dorsal deste PRD e não existia nas versões anteriores.

```bash
curl -sL -o ezdxf.tar.gz https://codeload.github.com/mozman/ezdxf/tar.gz/refs/tags/v1.4.4
tar xzf ezdxf.tar.gz && cd ezdxf-1.4.4/docs/source/dxfinternals
```

---

## 1. Objetivo

**Dar a um agente LLM domínio operacional sobre o formato DXF em si:** ler a estrutura, validar a integridade, normalizar a formatação, corrigir defeitos, converter entre versões e produzir arquivos conformes — por ferramentas determinísticas, sem escrever Python a cada vez.

O produto responde perguntas do tipo:

- Este arquivo é estruturalmente válido? Onde exatamente ele quebra?
- Que versão é, e o que se perde ao converter para outra?
- Qual a codificação, e há caracteres que não sobrevivem a ela?
- Há handles pendurados, donos órfãos, referências circulares?
- Os nomes de recurso são conformes? Colidem por case-insensitivity?
- Que dados de terceiros estão embutidos em XDATA/XRecord/AppData?
- As tabelas de recurso estão completas, ou há camada usada sem definição?
- A formatação gráfica é consistente — cores, linetypes, lineweights, BYLAYER/BYBLOCK?

### 1.1 As quatro camadas do formato

O DXF tem quatro camadas, e o servidor precisa operar em todas:

| Camada | O que é | Ferramentas |
|---|---|---|
| **Léxica** | Tags: código de grupo + valor, um por linha. Codificação, ASCII vs binário, limites de string | 6.2 |
| **Estrutural** | Seções, tabelas, handles, propriedade (ownership), referências | 6.3 |
| **Semântica** | Entidades, objetos, blocos, layouts, recursos nomeados | 6.4, 6.5 |
| **De apresentação** | Camadas, cores, linetypes, lineweights, estilos, transparência | 6.6 |

### 1.2 Fluxo canônico

```
abrir (com recuperação em camadas)
  → identificar versão, codificação, procedência
  → auditar integridade estrutural
  → mapear seções, tabelas, handles e propriedade
  → validar nomes de recurso e conformidade de versão
  → inventariar dados de terceiros (XDATA/XRecord/AppData)
  → normalizar formatação gráfica
  → converter versão com relatório de perda
  → salvar / renderizar para conferência
```

---

## 2. Mapa de cobertura — 79 módulos

**[N]** núcleo v1.0 · **[E]** estendido v1.0 · **[F]** futuro · **[X]** fora, com motivo

### 2.1 Formato e I/O — **prioridade máxima no v3**

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf` (new, readfile, read, readzip, decode_base64) | **N** | Abertura, criação, ZIP, base64 |
| `ezdxf.document` (Drawing, MetaData, export_json_tags, load_json_tags) | **N** | Documento; **JSON de tags = inspeção léxica sem sair do MCP** |
| `ezdxf.recover` (readfile, read, explore) | **N** | Três níveis de recuperação |
| `ezdxf.lldxf.const` (12 exceções) | **N** | Hierarquia de erro → mensagem acionável |
| `ezdxf.lldxf.extendedtags` / `.packedtags` (Tags, ExtendedTags, VertexArray) | **E** | **Acesso à camada léxica** — promovido de [X] no v2 |
| `ezdxf.comments` | **N** | Comentários (código 999) |
| `ezdxf.has_dxf_unicode` / `decode_dxf_unicode` | **N** | Escapes `\U+nnnn` |
| `ezdxf.r12strict` | **N** | Conformidade R12 Autodesk |
| `ezdxf.options` | **E** | Opções globais e arquivos de config |
| `ezdxf.tools.crypt` | **E** | "Criptografia" SAT — promovido, é formatação |

### 2.2 Estrutura do documento — **núcleo do v3**

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf.sections.header` (HeaderSection, CustomVars) | **N** | Variáveis `$*`, dados de usuário |
| `ezdxf.sections.classes` (ClassesSection, DXFClass) | **N** | **Seção CLASSES** — promovida; sem ela o AutoCAD recusa o arquivo |
| `ezdxf.sections.tables` / `.table` (10 classes) | **N** | As 9 tabelas de recurso |
| `ezdxf.sections.blocks` / `.entities` / `.objects` | **N** | Acesso por seção |
| `ezdxf.entitydb` (EntityDB, EntitySpace) | **N** | **Banco de handles** — promovido de [E] |
| `ezdxf.layouts` (Layouts, Modelspace, Paperspace, BlockLayout) | **N** | Layouts e sua relação com BLOCKS |
| `ezdxf.blkrefs` (BlockReferenceCounter, find_unreferenced_blocks) | **N** | Contagem de referência — ver risco R3 |
| `ezdxf.entities.dxfgroups` (DXFGroup, GroupCollection) | **E** | Grupos nomeados |
| `ezdxf.query` (EntityQuery) | **N** | Linguagem de consulta |
| `ezdxf.groupby` | **N** | Agrupamento por atributo |
| `ezdxf.select` (Window, Circle, Polygon, fence, PlanarSearchIndex) | **E** | Seleção espacial |
| `ezdxf.reorder` (ascending, descending) | **E** | Ordem de desenho (sort handles) |

### 2.3 Entidades e objetos

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf.entities` — 37 tipos gráficos | **N** | Inventário, atributos, subclasses, validação por versão |
| `ezdxf.entities` — 13 objetos não-gráficos | **N** | Dictionary, XRecord, Layout, PlotSettings, GeoData, ImageDef, MLeaderStyle, SpatialFilter, Sun, UnderlayDef, Placeholder |
| Tabelas: Layer, Linetype, Textstyle, DimStyle, AppID, UCS, View, VPort, BlockRecord, LayerOverrides | **N** | Entradas de recurso |
| Blocos: Block, EndBlk, Insert, AttDef, Attrib | **N** | Definição e referência |
| ACIS (Body, Region, Solid3d, Surface) | **F** | Só inspeção de metadados |

### 2.4 Dados customizados — **promovido a núcleo no v3**

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf.entities.xdata` (XData, XDataUserList, XDataUserDict) | **N** | XDATA por AppID |
| `ezdxf.entities.xdict` (ExtensionDict) | **N** | Dicionário de extensão |
| `ezdxf.entities.appdata` (AppData, Reactors) | **N** | AppData `{APPID ... }` e reatores persistentes |
| `ezdxf.urecord` (UserRecord, BinaryRecord) | **N** | XRecord tipado |

<cite index="1-1">Todo objeto de banco de dados tem: handle único, tabela XDATA opcional, tabela de reatores persistentes opcional e ponteiro de propriedade opcional para um dicionário de extensão</cite>. Essas quatro coisas são a superfície de extensão do formato — e é onde sistemas de terceiros escondem dados.

### 2.5 Geometria — suporte, não protagonista

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf.math` (~80 fn, 25 cls) | **N** | Vec2/Vec3, Matrix44, OCS/UCS, BoundingBox, bulge, `offset_vertices_2d` |
| `ezdxf.edgeminer` (22 fn) | **N** | Cadeias, loops, redes — **é análise estrutural da geometria** |
| `ezdxf.edgesmith` (16 fn) | **N** | DXF ↔ arestas, área, ponto-em-polígono |
| `ezdxf.bbox` (extents, multi_flat, multi_recursive, Cache) | **N** | Extensões |
| `ezdxf.transform` (9 fn + Logger) | **N** | Transformações com log de falha |
| `ezdxf.upright` | **N** | Reverter extrusão `(0,0,-1)` |
| `ezdxf.disassemble` (7 fn + Primitive) | **N** | Achatar blocos aninhados |
| `ezdxf.path` (~45 fn + Path) | **E** | Conversores, fillet, chamfer, geradores |
| `ezdxf.math.clipping` (Greiner-Hormann) | **E** | Boolean 2D |
| `ezdxf.math.clustering` / `.rtree` / `.triangulation` | **E** | dbscan, k_means, RTree, earcut |
| `ezdxf.math_construction_tools` | **E** | ConstructionLine/Circle/Arc/Ellipse/Box |
| `ezdxf.math.linalg` | **X** | Álgebra interna |

### 2.6 Formatação gráfica — **promovido a núcleo no v3**

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf.colors` (9 fn, RGB, RGBA) | **N** | ACI ↔ RGB, raw color, transparência, luminância |
| `ezdxf.gfxattribs` (GfxAttribs) | **N** | **Validador universal de atributo gráfico** |
| `ezdxf.enums` (16 enums) | **N** | Alinhamento, unidades, ACI, EndCaps, JoinStyle, SortEntities |
| `ezdxf.units` (conversion_factor, unit_name, angle_unit_name) | **N** | Unidades de documento e de bloco |
| `ezdxf.appsettings` (12 fn) | **E** | Recursos correntes, `update_extents`, `show_lineweight` |
| `ezdxf.addons.acadctb` (CTB/STB) | **E** | **Estilos de plotagem** — promovido: é formatação de saída |

### 2.7 Texto e fontes

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf.tools.text` (MTextEditor, plain_mtext, ~14 fn) | **N** | **Formatação inline de MTEXT** — códigos `\P \f \S \A \C \H` |
| `ezdxf.tools.text_size` | **E** | Medida de texto |
| `ezdxf.fonts.fonts` (~10 fn, 8 cls) | **E** | Resolução de fonte, cache, SHX vs TTF |
| `ezdxf.addons.MTextExplode` | **E** | MTEXT → TEXT |
| `ezdxf.addons.MTextSurrogate` | **E** | Substituto de MTEXT para R12 |
| `ezdxf.addons.text2path` | **E** | Texto → contorno |

### 2.8 Blocos e referências externas

| Módulo | | Uso |
|---|:-:|---|
| `ezdxf.addons.importer` | **N** | Importar entre documentos |
| `ezdxf.xref` (8 fn, ConflictPolicy, Loader) | **N** | **XREF completo** — promovido: é estrutura de documento |
| `ezdxf.xclip` (XClip, ClippingPath) | **E** | Recorte de referência — só 2D |
| `ezdxf.addons.dxf2code` | **E** | DXF → Python |

### 2.9 Render e conversão

| Módulo | | Uso |
|---|:-:|---|
| `drawing` — SVGBackend | **N** | Preview padrão, sem dependência |
| `drawing` — CustomJSONBackend / GeoJSONBackend | **N** | Geometria como JSON — o agente raciocina sobre ela |
| `drawing` — MatplotlibBackend / PyMuPdfBackend | **E** | PNG, PDF |
| `drawing` — DXFBackend | **E** | DXF achatado |
| `drawing` — Configuration, policies, Page, Recorder/Player | **E** | Controle fino de saída |
| `drawing` — PlotterBackend (HPGL/2) | **F** | — |
| `drawing` — PyQtBackend | **X** | Exige GUI |
| `ezdxf.render.forms` (24 fn) | **E** | Geradores 2D/3D |
| `ezdxf.render.hatching` | **E** | Hachura → linhas |
| `ezdxf.render.curves` / `.mesh` / `.arrows` / `.point` / `.trace` | **E** | Construções |
| `ezdxf.render.mleader` | **F** | — |
| `ezdxf.revcloud` | **E** | — |

### 2.10 Exportação

| Módulo | | Uso |
|---|:-:|---|
| `addons.r12export` | **N** | Qualquer versão → R12 |
| `addons.r12writer` | **E** | Escrita R12 em streaming |
| `addons.meshex` (STL/OFF/OBJ/PLY/SCAD/IFC4) | **E** | Troca de malha |
| `addons.iterdxf` | **F** | Streaming > 5 GB |
| `addons.odafc` | **F** | DWG — exige ODA File Converter |
| `addons.binpacking` | **F** | Nesting — **rebaixado de [N] no v2**: é produção, não formato |
| `addons.geo` | **F** | GIS |
| `addons.hpgl2.api` | **F** | HPGL/2 |
| `addons.tablepainter` | **F** | Tabelas desenhadas |
| `addons.gerber_D6673` | **X** | Nicho ASTM |
| `addons.openscad` / `.pycsg` / `.forms` / `.dwg` | **X** | Dependência externa, 3D fora do foco, ou demonstração |
| `ezdxf.acis` | **F** | Só inspeção SAT/SAB |

**Resumo:** 48 módulos **[N]** ou **[E]** · 14 **[F]** · 9 **[X]** com motivo.

---

## 3. Achados empíricos

ezdxf 1.4.4 / Python 3.12.3. Logs reais.

### 3.1 `[MEDIDO]` — `find_all_loops` falha com redes desconexas

```
tol=1e-09   redes=1 tamanhos=[4] find_all_loops=1
tol=0.05    redes=2 tamanhos=[2, 4] find_all_loops=0     ← ZERO
    rede de 4 arestas -> loops=1                          ← o loop EXISTE
```

> **REGRA:** `dxf_analyze_contours` **sempre** particiona com `Deposit.find_all_networks()` e busca **por rede**. Nunca sobre o depósito completo.

### 3.2 `[MEDIDO]` — `GAP_TOL` default é inútil em desenho real

Quadrado com gap de 0,02: `tol=0.01 → 0 loops` · `tol=0.05 → 1 loop`. O default `1e-9` nunca fecha desenho de CAD.

### 3.3 `[MEDIDO]` — pipeline base operacional

```
6 entidades aptas | 1 loop | área 5000.00 | perím 300.00 | polyline 5 vértices
audit: 0 erros, 0 correções | bbox (0,0,0) → (300.02, 50, 0)
```

### 3.4 `[MEDIDO]` — estado de camada é ignorado, e camada existe sem tabela

```
layers na TABELA : ['0', 'AUXILIAR', 'Defpoints', 'RASCUNHO']
layers EM USO    : ['AUXILIAR', 'CORTE', 'RASCUNHO']
-> 'CORTE' existe como layer mas NAO tem entrada na tabela: True

entidades iteradas: 3 | destas, em layer OFF ou FROZEN: 2
   AUXILIAR  on=False frozen=False
   RASCUNHO  on=True  frozen=True
```

Duas consequências estruturais:

1. **`doc.layers` não é a lista de camadas do desenho.** Listar camadas = entradas de tabela ∪ camadas referenciadas por entidades. A doc confirma: <cite index="1-1">o formato DXF não exige entrada de tabela para uma camada; sem entrada ela tem linetype Continuous, cor 7 e lineweight -3</cite>.
2. **Iterar devolve tudo, inclusive camada desligada e congelada** — <cite index="1-1">o ezdxf ignora todos os estados de camada</cite>. Análises e exportações precisam de `respect_layer_state`.

### 3.5 `[MEDIDO]` — o `audit` **detecta** ciclo de bloco

```
erros do audit:
   104 - Invalid block reference cycle detected in block "A".
   104 - Invalid block reference cycle detected in block "B".
```

Eu supus que não detectava e testei antes de escrever. **Detecta**, com o código `AuditError` 104. Portanto: **não reimplementar detecção de ciclo** — expor o código 104 do audit com destaque. Isso importa porque a doc é dura: <cite index="1-1">é possível criar definições cíclicas de bloco, e aplicações CAD não carregam o arquivo ou simplesmente travam</cite>.

### 3.6 `[MEDIDO]` — colisão de nome por case-insensitivity é bloqueada na criação

```
blocks  'PECA' + 'peca'  -> BLOQUEADO por ezdxf (DXFTableEntryError)
layers  'Corte' + 'CORTE' -> BLOQUEADO por ezdxf (DXFTableEntryError)
```

O ezdxf protege na criação. **Mas não na leitura**: um arquivo produzido por outro software pode conter a colisão. A doc explica o estrago: <cite index="1-1">nomes de bloco têm de ser únicos e são case-insensitive; havendo duas definições com o mesmo nome, o AutoCAD funde os blocos num só com propriedades imprevisíveis</cite>. Ferramenta de validação continua necessária — só que para arquivo **carregado**, não criado.

### 3.7 `[MEDIDO]` — codificação por versão

```
R12     $DWGCODEPAGE=ANSI_1252  encoding=cp1252  output=cp1252
R2000   $DWGCODEPAGE=ANSI_1252  encoding=cp1252  output=cp1252
R2007   $DWGCODEPAGE=ANSI_1252  encoding=cp1252  output=utf-8
R2018   $DWGCODEPAGE=ANSI_1252  encoding=cp1252  output=utf-8
```

O corte é em R2007: dali em diante a saída é UTF-8, mas **`$DWGCODEPAGE` continua declarando ANSI_1252**. Ferramenta de inspeção deve mostrar os três valores (`$DWGCODEPAGE`, `encoding`, `output_encoding`) e não confundir declaração com realidade.

### 3.8 `[MEDIDO]` — conversão de unidade tem ruído de ponto flutuante

```
fator M->CM : 100.0
fator IN->MM: 25.400000000101603
```
Arredondar na apresentação; nunca comparar por igualdade exata.

### 3.9 `[MEDIDO]` — boolean 2D e offset existem

```
greiner_hormann_uniao/diferenca/intersecao: 9 / 7 / 5 vértices
offset_vertices_2d(quadrado, +3, closed) -> [(3,3),(97,3),(97,47),(3,47)]
```
Correção ao PRD v1, que afirmava a ausência dos dois. `[MEDIR]` o comportamento do offset em polígono côncavo (risco de auto-interseção).

---

## 4. Regras do formato extraídas de `dxfinternals/`

Esta seção não existia nos PRDs anteriores. É a base das ferramentas 6.2 e 6.3.

### 4.1 Camada léxica

- <cite index="1-1">Uma tag DXF é um código de grupo inteiro numa linha e o valor na linha seguinte</cite>. Notação: `(código, valor)`.
- <cite index="1-1">Com os nomes de símbolo estendidos do DXF R2000, o limite de 255 caracteres subiu para 2049 bytes por linha; ainda assim é mais seguro ficar em 255 ou menos, porque não está claro se vale para todos os códigos de string e nem toda biblioteca de terceiros trata isso corretamente. Conteúdo de MTEXT e dados binários continuam divididos em pedaços de menos de 255 caracteres</cite>.
- **Tipo do valor é determinado pela faixa do código.** Tabela integral no doc; as faixas que o validador precisa conhecer:

| Faixa | Tipo | Nota |
|---|---|---|
| 0–9 | String | `0` estrutura · `1` texto primário · `2` nome · `5` handle · `6` linetype · `7` text style · `8` layer · `9` variável de header |
| 10–39 | Ponto 3D duplo | |
| 40–59, 110–149, 210–239, 460–469 | Float duplo | |
| 60–79, 170–179, 270–289, 370–389, 400–409 | Inteiro 16 bits | |
| 90–99, 420–429, 440–449 | Inteiro 32 bits | |
| 160–169 | Inteiro 64 bits | |
| 100, 102 | String (marcador de subclasse / grupo de app) | |
| 105 | Handle hex | **Só DIMSTYLE**, porque o código 5 já é DIMBLK |
| 290–299 | Booleano | |
| 310–319 | Binário em hex | |
| **320–329** | Ponteiro arbitrário | **NÃO** traduzido em INSERT/XREF |
| **330–339** | Soft-pointer | Traduzido |
| **340–349** | Hard-pointer | Traduzido |
| **350–359** | Soft-owner | Traduzido |
| **360–369** | Hard-owner | Traduzido |
| 999 | Comentário | Ignorado pelo carregador de tags |
| 1000–1071 | XDATA | `1005` = handle com semântica de soft-pointer |

### 4.2 Codificação

- <cite index="1-1">R2004 e anteriores são ASCII com a codificação definida por `$DWGCODEPAGE`, default `ANSI_1252` se ausente</cite>. Mapa completo: ANSI_874/932/936/949/950/1250–1258 → cp874, cp932, gbk, cp949, cp950, cp1250–cp1258.
- <cite index="1-1">A partir do R2007 o arquivo é UTF-8; `$DWGCODEPAGE` continua presente mas seu significado é incerto</cite>.
- <cite index="1-1">Caracteres fora da codificação escolhida são gravados como `\U+nnnn`, esquema que continua funcional</cite>.

### 4.3 Handles e propriedade

- <cite index="1-1">Handle é um valor hex único no arquivo, convencionalmente em maiúsculas, com até 16 dígitos hexadecimais</cite>.
- <cite index="1-1">De R10 a R12 handles eram opcionais, sinalizados por `$HANDLING=1`; de R13 em diante são obrigatórios e `$HANDLING` foi removido</cite>.
- <cite index="1-1">`$HANDSEED` deveria ser maior que o maior handle usado, mas não confie: o AutoCAD ignora esse valor</cite>.
- <cite index="1-1">A definição de handle é sempre `(5, ...)`, exceto nas entradas da tabela DIMSTYLE, que usam `(105, ...)` porque DIMSTYLE já tem um código 5 para DIMBLK</cite>.
- **Ponteiro ≠ propriedade.** <cite index="1-1">Ponteiro indica uso, não posse; propriedade significa responsabilidade. Um objeto pode ter qualquer número de ponteiros, mas apenas um dono</cite>.
- **Regra decisiva para purga:** <cite index="1-1">referências duras, sejam ponteiro ou dono, protegem o objeto de ser purgado; referências suaves não</cite>. <cite index="1-1">Definições de bloco e entidades complexas são donas duras de seus elementos; tabelas de símbolo e dicionários são donos suaves; POLYLINE é dona dura de seus VERTEX e SEQEND; INSERT é dona dura de seus ATTRIB e SEQEND</cite>.
- <cite index="1-1">Handles em XDATA com código 1005 têm semântica de soft-pointer e são traduzidos em merge; quando o AUDIT detecta um handle de XDATA que não corresponde a nenhuma entidade, considera erro e, ao corrigir, zera o handle</cite>.

### 4.4 Seções

Ordem canônica e obrigatoriedade:

| Seção | Desde | Obrigatória | Nota |
|---|---|---|---|
| HEADER | R10 | **R13+** | <cite index="1-1">Opcional em R12 e anteriores, mandatória desde R13</cite>. Tem de ser a primeira. Variável = `(9, $NOME)` + tags de valor |
| CLASSES | R13 | Condicional | <cite index="1-1">Algumas entidades exigem definição de classe ou o AutoCAD não abre o arquivo</cite>. <cite index="1-1">Nome de classe **não é único** — a chave tem de ser (nome, nome C++)</cite>. <cite index="1-1">Entidades CLASS não têm handle</cite> |
| TABLES | R10 | Sim | 9 tabelas. Handle da tabela em `(5,…)`, dono sempre `"0"`, marcador `AcDbSymbolTable`. <cite index="1-1">O contador `(70,…)` não é confiável e o AutoCAD o ignora</cite> |
| BLOCKS | R10 | Sim | <cite index="1-1">`*Model_Space` e `*Paper_Space` são reservados e vazios — o conteúdo está em ENTITIES. Os demais layouts ficam em `*Paper_Spacennn`</cite> |
| ENTITIES | R10 | Sim | Modelspace + paperspace ativo |
| OBJECTS | R13 | R13+ | <cite index="1-1">A documentação da Autodesk sobre a seção OBJECTS é muito rasa; boa parte do conhecimento é tentativa e erro</cite> |
| THUMBNAILIMAGE | R13 | Não | Preview, descartável |
| ACDSDATA | R2013 | Não | <cite index="1-1">Sem informação na referência DXF</cite> |

### 4.5 Modelo de dados por geração

| | R12 | R13+ |
|---|---|---|
| Referências | **Por nome.** INSERT→BLOCK pelo nome; TEXT→STYLE e LAYER pelo nome | **Por handle**, obrigatório |
| Layout de entidade | Tag `(67, 0\|1)`: 0 ou ausente = modelspace, 1 = paperspace | BLOCK_RECORD + LAYOUT |
| Conteúdo de bloco | Entre BLOCK e ENDBLK | Idem, com handles e donos |
| CLASSES / OBJECTS | Não existem | Existem |

<cite index="1-1">O R12 tem estrutura limpa e simples, o que explica por que a referência de 1992 segue amplamente usada e o AutoCAD ainda lê e escreve R12 — enquanto para R13/R14 o AutoCAD não tem suporte de escrita</cite>. Isso justifica ADR-14.

### 4.6 Blocos

- <cite index="1-1">O bloco é referenciado só pelo nome, tag `(2, nome)`; existe uma segunda tag `(3, nome2)` não documentada pela Autodesk — ignore</cite>.
- <cite index="1-1">Nomes de bloco são únicos e case-insensitive</cite> (achado 3.6).
- <cite index="1-1">Ciclos de definição — bloco A insere B e B insere A — fazem a aplicação CAD não carregar o arquivo ou travar</cite> (achado 3.5: o audit pega, código 104).

---

## 5. Decisões de arquitetura

| # | Decisão | Rejeitada | Motivo |
|---|---|---|---|
| ADR-1 | Python + FastMCP | TypeScript | ezdxf é Python |
| ADR-2 | Transporte stdio | HTTP | Local, monousuário, precisa do disco |
| ADR-3 | Sessão residente (`doc_id`) | Reabrir por chamada | ezdxf carrega o documento inteiro na memória |
| ADR-4 | Escrita nunca sobrescreve por default | In-place | Agente errando destrói arquivo de cliente |
| ADR-5 | `find_all_loops` sempre por rede | Depósito completo | Achado 3.1 |
| ADR-6 | `respect_layer_state` em análise e export | Iterar tudo | Achado 3.4 |
| ADR-7 | Camadas = tabela ∪ referenciadas | Só `doc.layers` | Achado 3.4 |
| ADR-8 | Carga em camadas: `readfile` → `recover` → `explore` | Sempre recover | Padrão "Try Hard" da doc |
| ADR-9 | **Validação estrutural = audit + verificações próprias** | Só audit | O audit cobre 64 códigos; nome case-colidente em arquivo carregado, conformidade de versão e limite de string ficam de fora |
| ADR-10 | **Nunca reimplementar o que o audit já faz** | Detector próprio de ciclo | Achado 3.5 — o audit pega com código 104 |
| ADR-11 | Purga guiada por dureza da referência | Contagem simples | 4.3 — referência dura protege, suave não |
| ADR-12 | Toda purga com `dry_run=true` default | Apagar direto | A doc avisa que dá para destruir o documento |
| ADR-13 | `GfxAttribs` como validador universal | Validação ad hoc | Já valida nome, ACI, lineweight, transparência |
| ADR-14 | **Mudança de versão é exportação com perda, sempre relatada** | Tratar como conversão | O ezdxf não é conversor de versão |
| ADR-15 | Operações geométricas devolvem entidade nova | Mutar in-place | Rastreabilidade |
| ADR-16 | **Acesso à camada léxica via `export_json_tags` e `Tags`** | Só objetos altos | Inspeção de código de grupo é requisito do v3 |

---

## 6. Catálogo de ferramentas — 92

Convenção: `dxf_{ação}_{recurso}`, snake_case, prefixo `dxf_`.
Parâmetros universais: `response_format` (`markdown`\|`json`), `limit`/`offset` em listagens, `respect_layer_state` (default `true`) em tudo que percorre geometria.

### 6.1 Sessão · 5

`dxf_open_document` (modo `auto`\|`fast`\|`recover`\|`explore`; `errors`: `surrogateescape`\|`ignore`\|`strict`; retorna `doc_id`, versão, upgrade aplicado, audit, `loaded_with`, avisos) · `dxf_new_document` · `dxf_close_document` · `dxf_list_documents` · `dxf_set_option`

### 6.2 Camada léxica — formatação bruta · 8

| Ferramenta | Base |
|---|---|
| `dxf_inspect_encoding` | `$DWGCODEPAGE`, `encoding`, `output_encoding`, versão. **Mostra os três** (achado 3.7). Mapa das 14 codepages |
| `dxf_find_encoding_issues` | Caracteres que não sobrevivem à codificação alvo; ocorrências de `\U+nnnn`; usa `has_dxf_unicode` / `decode_dxf_unicode` |
| `dxf_check_string_limits` | Strings > 255 e > 2049 bytes, por código de grupo. Sinaliza o risco de terceiros (4.1) |
| `dxf_dump_tags` | `document.export_json_tags` — tags cruas de uma entidade ou seção, com código, tipo inferido pela faixa e valor |
| `dxf_explain_group_code` | Tabela de 4.1: dado um código, devolve tipo, semântica, e se é traduzido em INSERT/XREF |
| `dxf_read_comments` | `ezdxf.comments` — código 999 |
| `dxf_strip_file` | Remove comentários e THUMBNAILIMAGE. **Só ASCII** |
| `dxf_detect_format` | ASCII vs binário, ZIP, base64, tamanho, contagem de linhas |

### 6.3 Estrutura e integridade · 14 — **o núcleo do v3**

| Ferramenta | Notas |
|---|---|
| **`dxf_audit`** | `doc.audit()` com os **64 códigos simbólicos** de `AuditError`, mensagem e handle. Destaque para o **104 — ciclo de bloco** (achado 3.5). Paginado |
| **`dxf_validate_structure`** | Suíte que o audit **não** cobre (ADR-9): seções presentes vs exigidas pela versão, HEADER como primeira seção, CLASSES faltando para entidades que a exigem, `$HANDSEED` vs maior handle, `$HANDLING` em R12 |
| `dxf_map_sections` | Presença, ordem e tamanho das 9 seções; contagem por seção |
| `dxf_inspect_header` | Variáveis `$*` agrupadas por tema, com `CustomVars` |
| `dxf_set_header_var` | Escrita validada de variável de cabeçalho |
| `dxf_list_tables` | As 9 tabelas com contagem real **e** o valor declarado em `(70,…)`, marcando divergência (o contador não é confiável) |
| `dxf_inspect_classes` | Seção CLASSES; chave `(nome, nome C++)` porque **nome não é único** (4.4) |
| `dxf_trace_handle` | Dado um handle: entidade, dono, quem aponta para ele, tipo de cada referência (arbitrária/soft/hard, pointer/owner) |
| `dxf_find_dangling_handles` | Referências para handles inexistentes, incluindo XDATA código 1005 |
| `dxf_analyze_ownership` | Árvore de propriedade; órfãos; objetos com mais de um dono |
| `dxf_check_purge_safety` | **ADR-11**: classifica cada candidato pela dureza da referência que o segura |
| `dxf_purge_unused` | `blkrefs` + tabelas. **`dry_run=true` default** |
| `dxf_inspect_entitydb` | Estatística do banco: total, por tipo, faixa de handles, colisões |
| `dxf_check_name_conformance` | Caracteres proibidos `< > / \ " : ; ? * = \`` · limite R12 de 31 caracteres · maiúsculas R12 · **colisão case-insensitive em arquivo carregado** (achado 3.6) |

### 6.4 Semântica: entidades, blocos, layouts · 13

`dxf_inspect_document` (panorama tipo `ezdxf info -v -s`) · `dxf_list_entities` · `dxf_query` · `dxf_get_entity` (atributos + subclasses + XDATA + dicionário de extensão + reatores) · `dxf_groupby` · `dxf_list_layouts` · `dxf_list_blocks` · `dxf_list_block_refs` (`BlockReferenceCounter`) · `dxf_find_unreferenced_blocks` · `dxf_create_block` · `dxf_insert_block` · `dxf_manage_attribs` (ATTDEF/ATTRIB) · `dxf_manage_paperspace` (layout, viewport, escala, `LayerOverrides`)

### 6.5 Recursos externos · 5

`dxf_import_from` (`addons.Importer`) · `dxf_manage_xref` (attach, define, detach, embed, load_modelspace/paperspace, write_block, `ConflictPolicy`) · `dxf_inspect_xref` (`xref.dxf_info` sem carregar) · `dxf_manage_xclip` (só 2D, sem recorte invertido) · `dxf_manage_groups` (**valida: grupo não pode estar em definição de bloco**)

### 6.6 Formatação gráfica · 13

| Ferramenta | Notas |
|---|---|
| `dxf_list_layers` | **ADR-7**: tabela ∪ referenciadas, marcando as sem entrada |
| `dxf_manage_layer` | Criar, renomear (com varredura de referências textuais), cor, linetype, lineweight, transparência, on/off/freeze/lock. Valida por `GfxAttribs` |
| `dxf_delete_layer` | Dois passos: entidades primeiro, entrada depois |
| `dxf_organize_layers` | Move entidades por regra |
| `dxf_manage_linetype` | Padrão simples e complexo (com texto e shape) |
| `dxf_manage_textstyle` | STYLE, SHX vs TTF |
| `dxf_manage_dimstyle` | DIMSTYLE e `DimStyleOverride` |
| `dxf_manage_appid` | APPID — pré-requisito de XDATA |
| `dxf_set_entity_attribs` | Lote validado por `GfxAttribs` |
| `dxf_analyze_formatting` | **Consistência**: quem é BYLAYER, BYBLOCK ou explícito; cores fora de paleta; lineweights inválidos; camadas sem definição |
| `dxf_convert_colors` | ACI ↔ RGB, raw color, transparência, luminância |
| `dxf_manage_plotstyles` | CTB/STB via `addons.acadctb` |
| `dxf_set_app_settings` | `appsettings` — **declarado como sugestão ao CAD, não garantia** |

### 6.7 Dados customizados · 7

`dxf_inventory_custom_data` (**varredura**: quais AppIDs, quantas entidades com XDATA, XRecords, dicionários de extensão, reatores — o mapa dos dados de terceiros) · `dxf_get_xdata` · `dxf_set_xdata` (`XDataUserList` / `XDataUserDict`) · `dxf_get_extension_dict` · `dxf_manage_xrecord` (`urecord.UserRecord`) · `dxf_manage_appdata` · `dxf_manage_reactors`

### 6.8 Unidades, escala e conformidade de versão · 7

| Ferramenta | Notas |
|---|---|
| `dxf_inspect_units` | `$INSUNITS`, `$MEASUREMENT`, `$LUNITS`, `$AUNITS` + unidade de cada bloco |
| `dxf_set_units` | Declara. **Não** reescala. Aviso explícito na resposta |
| `dxf_convert_units` | `units.conversion_factor` + escala real. Distinta da anterior |
| `dxf_check_block_scale` | Bloco com unidade ≠ do documento sem escala compensatória no INSERT — **nenhuma conversão é implícita** |
| `dxf_check_version_compat` | Simula versão alvo e lista o que degrada. Não escreve |
| `dxf_check_r12_compat` | Caso especial do anterior, com as regras de nome R12 |
| `dxf_check_acad_compat` | CLASSES exigidas, nomes, entidades que o AutoCAD recusa |

### 6.9 Análise geométrica estrutural · 9

**`dxf_analyze_contours`** (ADR-5, ver 6.9.1) · **`dxf_sweep_tolerance`** · `dxf_find_duplicates` · `dxf_check_2d_purity` · `dxf_measure_extents` (`bbox` com `Cache`) · `dxf_measure_geometry` · `dxf_normalize_extrusions` (`upright`) · `dxf_flatten_to_2d` · `dxf_disassemble` (`recursive_decompose`, relatando os tipos ignorados: ACIS, XREF, UNDERLAY, ACAD_TABLE, RAY, XLINE)

#### 6.9.1 `dxf_analyze_contours`

```python
ents = filtrar(layout, layers, respect_layer_state)     # ADR-6
fechadas = [e for e in ents if es.is_closed_entity(e)]  # CIRCLE/SOLID/TRACE à parte
cand  = list(es.filter_edge_entities(ents))
edges = list(es.edges_from_entities_2d(cand, gap_tol=gap_tol))
dep   = em.Deposit(edges, gap_tol=gap_tol)

for net in dep.find_all_networks():                     # ADR-5 — SEMPRE particionar
    sub = em.Deposit(list(net), gap_tol=gap_tol)
    try:
        loops, parcial = em.find_all_loops(sub, timeout=timeout), False
    except em.TimeoutError as exc:
        loops, parcial = exc.solutions, True             # usa o parcial E sinaliza
    registrar(loops, sub.find_leafs(), sub.max_degree, parcial)
```

Regras: `find_all_loops` é backtracking O(n!) — o timeout **vai** disparar; use `TimeoutError.solutions` e **marque como incompleto**. CIRCLE, SOLID e TRACE não viram aresta; sem contá-los à parte o relatório nega furos num desenho cheio deles. Junção (grau > 2) é ambiguidade, não erro — reporte quantidade e posição.

### 6.10 Geometria: transformação e construção · 9

`dxf_close_contours` · `dxf_transform` (com `Logger` de falhas) · `dxf_convert_to_path` (`max_sagitta`) · `dxf_offset_contour` (normaliza orientação antes; declara a direção obtida) · `dxf_boolean_2d` (Greiner-Hormann) · `dxf_fillet_corners` · `dxf_chamfer_corners` · `dxf_explode_blocks` · `dxf_select_*` (window, circle, polygon, fence, chained — agrupadas numa ferramenta com `mode`)

### 6.11 Texto · 6

`dxf_add_text` (TEXT/MTEXT com `MTextEditor`) · `dxf_extract_text` (`plain_mtext` / `plain_text`) · `dxf_inspect_mtext_formatting` (**códigos inline**: `\P \f \S \A \C \H \W \Q`, pilhas, cor e altura embutidas) · `dxf_explode_mtext` · `dxf_text_to_contour` (`text2path`) · `dxf_manage_fonts` (resolução, cache, SHX vs TTF, fontes ausentes)

### 6.12 Render e verificação · 6

`dxf_render_svg` (default, sem dependência) · `dxf_render_png` · `dxf_render_pdf` · `dxf_render_json` (`CustomJSONBackend` / `GeoJSONBackend` — **o agente raciocina sobre a geometria**) · `dxf_configure_render` (as 8 policies) · `dxf_zoom_extents`

### 6.13 Exportação · 8

`dxf_save` (exige `overwrite=true`) · `dxf_save_as` (**com relatório de degradação, ADR-14**) · `dxf_export_r12_strict` (`r12export` + `r12strict.make_acad_compatible`, **sobre cópia** — `translate_names` é destrutivo) · `dxf_export_json_tags` · `dxf_export_mesh` (STL/OBJ/OFF/PLY) · `dxf_generate_code` (`dxf2code`) · `dxf_export_binary` (DXF binário) · `dxf_export_zip`

### 6.14 Criação · 5

`dxf_add_entities` (lote) · `dxf_add_form` (`render.forms`) · `dxf_add_path_shape` (`path`: rect, ngon, star, gear, helix, wedge) · `dxf_add_dimension` (7 tipos) · `dxf_add_hatch` (contorno de polyline ou edge path, padrões)

---

## 7. Anotações

| Grupo | readOnly | destructive | idempotent | openWorld |
|---|:-:|:-:|:-:|:-:|
| 6.2, 6.3 (exceto purge), 6.4 leitura, 6.7 leitura, 6.8 checks, 6.9 | ✅ | ❌ | ✅ | ❌ |
| 6.3 purge, 6.6, 6.7 escrita, 6.10, 6.13 | ❌ | ✅ | ❌ | ❌ |
| 6.12 render | ❌ | ❌ | ✅ | ❌ |
| 6.14 criação | ❌ | ❌ | ❌ | ❌ |

`openWorldHint` é `false` em tudo.

---

## 8. Projeto

```
ezdxf_mcp/
├── PRD.md · pyproject.toml · README.md · .env.example
├── src/ezdxf_mcp/
│   ├── server.py · config.py · session.py
│   ├── validation.py · formatting.py · errors.py · layers.py
│   └── tools/
│       ├── documents.py  lexical.py    structure.py   semantics.py
│       ├── xrefs.py      graphics.py   customdata.py  units.py
│       ├── geometry.py   text.py       render.py      export.py
│       └── create.py
├── tests/fixtures/make_fixtures.py + 14 DXFs gerados
└── evals/evaluation.xml
```

### 8.1 `pyproject.toml`

```toml
[project]
name = "ezdxf-mcp"
version = "3.0.0"
requires-python = ">=3.10"
dependencies = ["mcp[cli]>=1.2.0", "ezdxf>=1.4.4", "pydantic>=2.9"]

[project.optional-dependencies]
render = ["matplotlib>=3.9", "pymupdf>=1.24"]
dev    = ["pytest>=8.3", "pytest-asyncio>=0.24", "mypy>=1.13", "ruff>=0.8"]
all    = ["ezdxf-mcp[render]"]

[project.scripts]
ezdxf-mcp = "ezdxf_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 8.2 Comandos

```bash
mkdir -p ~/projects/ezdxf_mcp && cd ~/projects/ezdxf_mcp
uv venv && source .venv/bin/activate
uv pip install -e ".[all,dev]"

python -c "import ezdxf; print(ezdxf.__version__)"
ezdxf -V                                  # versão + C-extensions
ezdxf info -v -s tests/fixtures/*.dxf     # referência de conferência
ezdxf audit -s tests/fixtures/corrompido.dxf
ezdxf strip -b -t arquivo.dxf
ezdxf draw -o /tmp/preview.svg arquivo.dxf
```

### 8.3 `.env.example`

```bash
EZDXF_MCP_WORKSPACE=~/dxf-workspace
EZDXF_MCP_MAX_DOCS=8
EZDXF_MCP_MAX_FILE_MB=500
EZDXF_MCP_DEFAULT_TIMEOUT=60
EZDXF_MCP_DEFAULT_GAP_TOL=0.01
EZDXF_MCP_RESPECT_LAYER_STATE=true
EZDXF_MCP_LOG_LEVEL=INFO
EZDXF_DISABLE_C_EXT=          # vazio: C-extensions dão o ganho de performance
```

### 8.4 Registro

```json
{"mcpServers": {"ezdxf": {
  "command": "/home/USUARIO/projects/ezdxf_mcp/.venv/bin/ezdxf-mcp",
  "env": {"EZDXF_MCP_WORKSPACE": "/home/USUARIO/dxf-workspace"}}}}
```

---

## 9. Esqueleto

```python
# src/ezdxf_mcp/server.py
import logging, sys
from mcp.server.fastmcp import FastMCP

# stdio: log SEMPRE em stderr — stdout é o canal do protocolo
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
mcp = FastMCP("ezdxf_mcp")

from .tools import (documents, lexical, structure, semantics, xrefs,   # noqa: E402
                    graphics, customdata, units, geometry, text,
                    render, export, create)

def main() -> None:
    mcp.run()
```

```python
# src/ezdxf_mcp/tools/structure.py  (trecho — ADR-9 e ADR-11)
from ezdxf.lldxf import const

# Seções exigidas por versão (4.4)
SECOES_OBRIGATORIAS = {
    "AC1009": {"TABLES", "BLOCKS", "ENTITIES"},                        # R12
    "R13+":   {"HEADER", "CLASSES", "TABLES", "BLOCKS",
               "ENTITIES", "OBJECTS"},
}

# Faixas de código de grupo → semântica de referência (4.1)
FAIXAS_REFERENCIA = {
    range(320, 330): ("arbitrary", False),   # NÃO traduzido em INSERT/XREF
    range(330, 340): ("soft_pointer", True),
    range(340, 350): ("hard_pointer", True),
    range(350, 360): ("soft_owner",   True),
    range(360, 370): ("hard_owner",   True),
}

def dureza_da_referencia(codigo: int) -> tuple[str, bool] | None:
    """4.3: referência dura protege da purga; suave não."""
    for faixa, info in FAIXAS_REFERENCIA.items():
        if codigo in faixa:
            return info
    return None


def validar_estrutura(doc) -> list[dict]:
    """ADR-9: só o que o audit NÃO cobre. Nunca reimplementar ciclo de bloco
    (achado 3.5 — o audit pega com AuditError 104)."""
    achados = []

    # $HANDSEED vs maior handle real — a doc avisa que o AutoCAD ignora
    seed = doc.header.get("$HANDSEED", "0")
    maior = max((int(h, 16) for h in doc.entitydb.keys() if h), default=0)
    if int(str(seed), 16) <= maior:
        achados.append({"check": "handseed", "severity": "warning",
                        "message": f"$HANDSEED ({seed}) <= maior handle ({maior:X})"})

    # colisão case-insensitive em arquivo CARREGADO (achado 3.6:
    # o ezdxf bloqueia na criação, mas não na leitura)
    for nome_tab, tabela in (("LAYER", doc.layers), ("BLOCK", doc.blocks),
                             ("LTYPE", doc.linetypes), ("STYLE", doc.styles)):
        vistos: dict[str, str] = {}
        for entrada in tabela:
            n = entrada.dxf.name if hasattr(entrada, "dxf") else entrada.name
            k = n.upper()
            if k in vistos:
                achados.append({
                    "check": "name_collision", "severity": "error",
                    "message": (f"{nome_tab}: '{vistos[k]}' e '{n}' colidem "
                                f"(nomes são case-insensitive); o AutoCAD funde "
                                f"as definições com propriedades imprevisíveis")})
            vistos[k] = n
    return achados
```

```python
# src/ezdxf_mcp/layers.py  — ADR-6 e ADR-7
def camadas_ocultas(doc) -> set[str]:
    """O CAD não as mostra; o ezdxf as devolve ao iterar (achado 3.4)."""
    return {l.dxf.name for l in doc.layers if (not l.is_on()) or l.is_frozen()}

def iter_visiveis(layout, doc, *, respeitar_estado: bool = True):
    if not respeitar_estado:
        yield from layout; return
    ocultas = camadas_ocultas(doc)
    for e in layout:
        if e.dxf.get("layer", "0") not in ocultas:
            yield e

def todas_as_camadas(doc, layout=None) -> dict[str, bool]:
    """ADR-7: camada existe sem entrada na tabela. nome -> tem_entrada."""
    nomes = {l.dxf.name: True for l in doc.layers}
    for lay in ([layout] if layout else doc.layouts):
        for e in lay:
            nomes.setdefault(e.dxf.get("layer", "0"), False)
    return nomes
```

---

## 10. Testes

| Nível | Alvo | Arquivo |
|---|---|---|
| Unitário | Travessia de caminho, symlink, absoluto externo | `test_validation.py` |
| Unitário | Paginação, formatação, erro acionável | `test_formatting.py` |
| Unitário | `dureza_da_referencia` nas 5 faixas de código | `test_structure.py` |
| **Regressão** | **3.1** — `multi_rede.dxf`: ≥1 loop com `gap_tol=0.05` | `test_geometry.py` |
| **Regressão** | **3.2** — `gap_002.dxf`: 0 loops em 0.01, 1 em 0.05 | `test_geometry.py` |
| **Regressão** | **3.4a** — `camadas_ocultas.dxf`: 3 entidades, 1 visível | `test_layers.py` |
| **Regressão** | **3.4b** — camada usada sem entrada de tabela aparece na listagem | `test_layers.py` |
| **Regressão** | **3.5** — `ciclo_blocos.dxf`: audit reporta código 104 | `test_structure.py` |
| **Regressão** | **3.6** — `nome_colidente.dxf` **carregado** dispara `name_collision` | `test_structure.py` |
| **Regressão** | **3.7** — R2000 dá `output=cp1252`, R2007 dá `utf-8` | `test_lexical.py` |
| Integração | Ciclo: abrir → auditar → validar → normalizar → R12 → SVG | `test_pipeline.py` |
| Integração | `corrompido.dxf` carrega por fallback com `loaded_with="recover"` | `test_session.py` |
| Manual | `npx @modelcontextprotocol/inspector .venv/bin/ezdxf-mcp` | — |
| Estático | `mypy src/` · `ruff check src/` | — |

Fixtures **geradas por script**, nunca arquivo de cliente. As de arquivo defeituoso (nome colidente, handle pendurado, seção faltando) são escritas como texto DXF bruto, já que o ezdxf impede criá-las pela API.

---

## 11. Avaliação

`evals/evaluation.xml`, 10 perguntas independentes, somente leitura, verificáveis, estáveis. Cobertura obrigatória:

1. Codificação real vs declarada (3.7)
2. Semântica de um código de grupo específico (4.1)
3. Rastreio de handle e tipo de referência (4.3)
4. Handle pendurado
5. Ciclo de bloco via audit 104 (3.5)
6. Colisão de nome case-insensitive (3.6)
7. Camada usada sem entrada de tabela (3.4b)
8. Entidades em camada oculta (3.4a)
9. Degradação ao converter versão
10. Inventário de dados de terceiros (XDATA por AppID)

---

## 12. Fluxo de referência

```
dxf_open_document(arquivo.dxf)
dxf_detect_format                 → ASCII/binário, tamanho
dxf_inspect_encoding              → declarada vs real
dxf_inspect_document              → versão, upgrade, contagens
dxf_audit                         → 64 códigos, inclusive 104
dxf_validate_structure            → o que o audit não cobre
dxf_map_sections                  → seções presentes vs exigidas
dxf_find_dangling_handles         → referências quebradas
dxf_check_name_conformance        → colisões e caracteres proibidos
dxf_inventory_custom_data         → dados de terceiros embutidos
dxf_analyze_formatting            → BYLAYER/BYBLOCK, cores, lineweights
dxf_list_layers                   → tabela ∪ referenciadas
dxf_inspect_units                 → documento e blocos
dxf_check_version_compat(R12)     → o que se perde
dxf_check_purge_safety            → o que é seguro remover
dxf_purge_unused(dry_run)         → simulação
dxf_export_r12_strict             → saída conforme
dxf_render_svg                    → conferência visual
```

---

## 13. Marcos

| # | Escopo | Aceite |
|---|---|---|
| **0** | Fundação: projeto, sessão, validação de caminho, formatação, erros + `dxf_open_document` | Inspetor MCP abre fixture; `test_validation.py` passa |
| **1** | **Camada léxica** (6.2) | `dxf_inspect_encoding` distingue R2000 de R2007 (regressão 3.7); `dxf_dump_tags` mostra código, tipo e valor |
| **2** | **Estrutura e integridade** (6.3) | Regressões 3.5 e 3.6 passam; `dxf_trace_handle` classifica as 5 faixas de referência |
| **3** | Semântica e recursos externos (6.4, 6.5) | `dxf_inspect_document` bate com `ezdxf info -v -s` lado a lado |
| **4** | Formatação gráfica e dados customizados (6.6, 6.7) | Regressões 3.4a e 3.4b; `dxf_inventory_custom_data` acha XDATA por AppID |
| **5** | Unidades, versão, análise geométrica (6.8, 6.9) | Regressões 3.1 e 3.2; `dxf_check_version_compat` relata degradação |
| **6** | Geometria, texto, render, export, criação (6.10–6.14) + evals + README | Fluxo da seção 12 completo sem intervenção; 10 perguntas respondidas |

---

## 14. Riscos

| # | Risco | Prob. | Impacto | Mitigação |
|---|---|:-:|:-:|---|
| R1 | `find_all_loops` O(n!) estourar | Alta | Alto | Partição por rede; timeout; `TimeoutError.solutions`; `find_all_simple_chains` como pré-redução |
| R2 | Memória com DXF grande | Média | Alto | Teto de docs e tamanho; `bbox.Cache`; `iterdxf` fica para v1.1 |
| R3 | **Purga destruir o documento** | Média | **Alto** | ADR-11 (dureza da referência) + ADR-12 (`dry_run`). A doc avisa que não há garantia de que todo software siga as regras de referência |
| R4 | **Reescrever arquivo carregado em modo recover** | Média | **Alto** | A doc avisa que isso pode gerar DXF inválido ou perder informação. Marcar a sessão; exigir confirmação; expor `errors="strict"` |
| R5 | Cortar/exportar geometria de camada oculta | Alta se não tratado | Alto | ADR-6 |
| R6 | Confundir codificação declarada com real | Alta | Médio | 6.2 mostra os três valores sempre |
| R7 | Contagem de furos errada por ignorar CIRCLE | Alta se não tratado | Alto | `is_closed_entity()` conta à parte |
| R8 | Conversão de versão degradar em silêncio | Média | Alto | ADR-14: relatório obrigatório |
| R9 | Sobrescrever arquivo do cliente | Baixa | **Alto** | ADR-4 + workspace confinado |
| R10 | Reimplementar validação que o audit já faz | **Alta** | Médio | ADR-10 e achado 3.5 — testar antes de escrever detector próprio |
| R11 | Bloco em unidade divergente | Média | Alto | `dxf_check_block_scale`; nenhuma conversão é implícita |
| R12 | Multi-path sem orientação detectável | Média | Médio | Detectar `has_sub_paths` antes de operação orientada |
| R13 | Offset em polígono côncavo auto-interseccionar | Alta | Médio | `[MEDIR]` no Marco 6; o ezdxf não limpa o offset |
| R14 | Matplotlib/PyMuPDF ausentes | Média | Baixo | SVG não depende deles; degradar com aviso |

---

## 15. Definição de pronto

1. `pytest` inteiro passa, com as **7 regressões** dos achados 3.1, 3.2, 3.4a, 3.4b, 3.5, 3.6, 3.7.
2. `mypy src/` e `ruff check src/` limpos.
3. Inspetor MCP lista as 92 ferramentas com descrição e schema corretos.
4. O fluxo da seção 12 roda ponta a ponta num DXF real, sem intervenção.
5. 10 perguntas de avaliação respondidas corretamente.
6. Nenhuma ferramenta declara sucesso sem log de runtime.
7. Todo módulo **[N]** ou **[E]** da seção 2 é exercitado por ao menos uma ferramenta, **ou** tem uma linha no README dizendo por que não.
8. README com instalação, registro e as cinco operações mais comuns.

---

## 16. Aplicações derivadas — fora do núcleo

Estavam no v2 como núcleo. São reais e o ezdxf as suporta, mas são **produção**, não formato. Ficam para v1.1, construídas sobre este servidor:

| Aplicação | Base disponível |
|---|---|
| Preparação CAM | `offset_vertices_2d` (compensação de ferramenta), `math.clipping` (boolean 2D), `reorder` (ordem de corte) |
| Nesting de chapa | `addons.binpacking` — verificado: 12 peças 400×300 em 2440×1220, 48,4% de aproveitamento |
| Gravação de texto | `addons.text2path` — verificado: "MEKATRONIS" → 13 contornos |
| Desbaste por hachura | `render.hatching` — verificado: 100×50 a passo 2 mm → 25 linhas |
| Orçamento | `bbox`, `edgeminer.length`, `edgesmith.loop_area` |

---

## 17. Fora de escopo, com motivo

| Item | Motivo | Quando |
|---|---|---|
| G-code / toolpath | O ezdxf não é kernel CAD | Projeto separado |
| DWG nativo | Exige ODA File Converter externo | v1.1 via `odafc` |
| DXF > 1 GB | Exige `iterdxf`, acesso por streaming | v1.2 |
| Criar/editar ACIS | O ezdxf não cria nem edita geometria ACIS | Nunca |
| PyQtBackend, visualizador | Exige GUI; incompatível com stdio | Nunca |
| OpenSCAD, PyCSG | Dependência externa, foco 3D | Nunca |
| Gerber D6673 | Nicho ASTM | Nunca |
| HPGL/2, geo/GIS, TablePainter | Reais, fora do eixo formato | v1.1+ |

---

## Referências

- Documentação: https://ezdxf.readthedocs.io/en/stable/
- **Base do v3 — DXF Internals:** [File Structure](https://ezdxf.readthedocs.io/en/stable/dxfinternals/filestructure.html) · [Data Model](https://ezdxf.readthedocs.io/en/stable/dxfinternals/datamodel.html) · [DXF Tags](https://ezdxf.readthedocs.io/en/stable/dxfinternals/dxftags.html) · [Handles](https://ezdxf.readthedocs.io/en/stable/dxfinternals/handles.html) · [File Encoding](https://ezdxf.readthedocs.io/en/stable/dxfinternals/fileencoding.html) · [Block Management](https://ezdxf.readthedocs.io/en/stable/dxfinternals/block_management.html) · [Layout Management](https://ezdxf.readthedocs.io/en/stable/dxfinternals/layout_management.html)
- Estrutura: [Sections](https://ezdxf.readthedocs.io/en/stable/sections/index.html) · [Tables](https://ezdxf.readthedocs.io/en/stable/tables/index.html) · [Layouts](https://ezdxf.readthedocs.io/en/stable/layouts/index.html) · [Block References](https://ezdxf.readthedocs.io/en/stable/blkrefs.html)
- Dados customizados: [XDATA](https://ezdxf.readthedocs.io/en/stable/xdata.html) · [AppData](https://ezdxf.readthedocs.io/en/stable/appdata.html) · [Extension Dictionary](https://ezdxf.readthedocs.io/en/stable/xdict.html) · [XRecord](https://ezdxf.readthedocs.io/en/stable/user_record.html)
- Recuperação e conformidade: [Recover](https://ezdxf.readthedocs.io/en/stable/drawing/recover.html) · [r12strict](https://ezdxf.readthedocs.io/en/stable/r12strict.html)
- Geometria: [EdgeMiner](https://ezdxf.readthedocs.io/en/stable/edgeminer.html) · [EdgeSmith](https://ezdxf.readthedocs.io/en/stable/edgesmith.html) · [Path](https://ezdxf.readthedocs.io/en/stable/path.html)
- Código: https://github.com/mozman/ezdxf
