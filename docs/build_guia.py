"""
Genera docs/guia-de-usuario.pdf (reportlab).  Uso:  python docs/build_guia.py
Texto en español; solo fuentes estándar de PDF (sin símbolos Unicode fuera de Latin-1).
"""
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ORANGE = colors.HexColor("#F26513")
DARK = colors.HexColor("#01050D")
RED = colors.HexColor("#731702")
GREY = colors.HexColor("#64748B")
LIGHT = colors.HexColor("#F2F2F2")
AMBER_BG = colors.HexColor("#FFF7ED")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guia-de-usuario.pdf")

ss = getSampleStyleSheet()
BODY = ParagraphStyle("Body", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5, leading=15, textColor=DARK, spaceAfter=6)
H1 = ParagraphStyle("H1", parent=BODY, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=DARK, spaceBefore=4, spaceAfter=10)
H2 = ParagraphStyle("H2", parent=BODY, fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=ORANGE, spaceBefore=12, spaceAfter=5)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=9, leading=12, textColor=GREY)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=9.5, leading=12.5, spaceAfter=0)
CELLB = ParagraphStyle("CellB", parent=CELL, fontName="Helvetica-Bold")
CELLH = ParagraphStyle("CellH", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=14, bulletIndent=3, spaceAfter=3)
STEP = ParagraphStyle("Step", parent=BODY, leftIndent=18, bulletIndent=0, spaceAfter=4)
COVER_T = ParagraphStyle("CoverT", parent=H1, fontSize=34, leading=40, alignment=TA_CENTER, textColor=colors.white)
COVER_S = ParagraphStyle("CoverS", parent=BODY, fontSize=14, leading=20, alignment=TA_CENTER, textColor=colors.HexColor("#CBD5E1"))
TOC1 = ParagraphStyle("TOC1", parent=BODY, fontSize=11, leading=20, leftIndent=0)


def p(text, style=BODY):
    return Paragraph(text, style)


def bullets(items):
    return [Paragraph(t, BULLET, bulletText="-") for t in items]


def steps(items):
    return [Paragraph(t, STEP, bulletText=f"{i}.") for i, t in enumerate(items, 1)]


def table(rows, widths, header=True):
    data = [[Paragraph(str(c), CELLH if (header and r == 0) else CELL) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), DARK)]
        style += [("BACKGROUND", (0, r), (-1, r), LIGHT) for r in range(2, len(rows), 2)]
    t.setStyle(TableStyle(style))
    return t


def note(text, title="Importante", color=ORANGE):
    box = Table([[Paragraph(f"<b>{title}:</b> {text}", CELL)]], colWidths=[16.4 * cm])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AMBER_BG), ("LINEBEFORE", (0, 0), (0, -1), 3, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return [Spacer(1, 4), box, Spacer(1, 8)]


class Doc(BaseDocTemplate):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[Frame(0, 0, A4[0], A4[1], 0, 0, 0, 0)], onPage=self.cover_bg),
            PageTemplate(id="body", frames=[Frame(2.3 * cm, 2.2 * cm, A4[0] - 4.6 * cm, A4[1] - 4.4 * cm, id="f")], onPage=self.footer),
        ])

    @staticmethod
    def cover_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(DARK)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setFillColor(ORANGE)
        canvas.rect(0, A4[1] * 0.42, A4[0], 6, fill=1, stroke=0)
        canvas.restoreState()

    @staticmethod
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas.line(2.3 * cm, 1.7 * cm, A4[0] - 2.3 * cm, 1.7 * cm)
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(GREY)
        canvas.drawString(2.3 * cm, 1.2 * cm, "Stats Basketball - Guía de usuario")
        canvas.drawRightString(A4[0] - 2.3 * cm, 1.2 * cm, f"Página {doc.page - 1}")
        canvas.restoreState()

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name == "H1":
            text = f.getPlainText()
            key = f"h1-{self.seq.nextf('h1')}"
            self.canv.bookmarkPage(key)
            self.notify("TOCEntry", (0, text, self.page - 1, key))


def build():
    from reportlab.platypus import NextPageTemplate

    s = []
    # ── Portada ──────────────────────────────────────────────────────────────
    s += [Spacer(1, 7.2 * cm), p("Stats Basketball", COVER_T), Spacer(1, 10),
          p("Guía de usuario", COVER_S), Spacer(1, 6),
          p("Mesa de control, torneos y vista en vivo", COVER_S),
          Spacer(1, 9.5 * cm), p(f"Edición {date.today():%d/%m/%Y}", ParagraphStyle("c", parent=COVER_S, fontSize=10)),
          NextPageTemplate("body"), PageBreak()]

    # ── Índice ───────────────────────────────────────────────────────────────
    toc = TableOfContents()
    toc.levelStyles = [TOC1]
    toc.dotsMinLevel = 0
    s += [p("Contenido", ParagraphStyle("TocTitle", parent=H1)), toc, PageBreak()]

    # ── 1 ────────────────────────────────────────────────────────────────────
    s += [p("1. Qué es Stats Basketball", H1),
          p("Stats Basketball es una aplicación web para llevar las estadísticas de un partido de baloncesto "
            "<b>en tiempo real</b>: marcador, cronómetro, faltas, cambios de jugador y estadísticas individuales. "
            "También organiza torneos con tabla de posiciones automática y ofrece una página pública para que "
            "los espectadores sigan el partido desde su celular."),
          p("Funciones principales", H2)]
    s += bullets([
        "<b>Mesa de control</b> para el anotador: registra cada acción con un toque.",
        "<b>Equipos y jugadores</b>: plantillas reutilizables en todos los partidos.",
        "<b>Torneos</b>: fases, grupos y tabla de posiciones que se actualiza sola.",
        "<b>Resumen del partido</b>: box score completo y descarga en CSV (Excel).",
        "<b>Vista pública en vivo</b>: sin necesidad de iniciar sesión.",
    ])
    s += [p("Quién usa cada parte", H2),
          table([
              ["Perfil", "Qué hace", "Rol en el sistema"],
              ["Espectador", "Mira marcador y estadísticas en vivo", "Sin cuenta (página pública)"],
              ["Anotador / mesa", "Opera el partido: titulares, reloj, anotaciones, cambios", "scorer"],
              ["Organizador", "Crea equipos, jugadores, partidos y torneos; revisa la auditoría", "admin"],
          ], [3.4 * cm, 8.2 * cm, 4.8 * cm]), PageBreak()]

    # ── 2 ────────────────────────────────────────────────────────────────────
    s += [p("2. Primeros pasos", H1), p("Iniciar sesión", H2)]
    s += steps([
        "Abre la dirección de la aplicación que te dio el organizador.",
        "Escribe tu correo y contraseña y pulsa <b>Ingresar al panel</b>.",
        "Si tus datos son correctos llegarás al <b>Panel de administración</b>.",
    ])
    s += note("Si olvidaste tu contraseña o necesitas una cuenta, pídesela al administrador. "
              "La cuenta también define lo que puedes hacer (ver sección 10).", "Cuentas")
    s += [p("El panel de inicio", H2),
          p("Desde el panel de inicio accedes a las acciones principales:"),
          table([
              ["Botón", "Para qué sirve"],
              ["Nuevo partido", "Crear un partido (jugar ahora o programarlo)"],
              ["Ver equipos", "Consultar y administrar equipos y jugadores"],
              ["Acciones rápidas", "Accesos directos a partidos y torneos"],
          ], [5 * cm, 11.4 * cm]),
          p("Cerrar sesión", H2),
          p("Usa el botón de cerrar sesión del panel. Si tu sesión caduca, la aplicación te devolverá "
            "automáticamente a la pantalla de ingreso."), PageBreak()]

    # ── 3 ────────────────────────────────────────────────────────────────────
    s += [p("3. Equipos y jugadores", H1),
          p("Antes de crear un partido necesitas al menos dos equipos con jugadores registrados "
            "(un partido necesita entre <b>5 y 12 jugadores</b> por equipo).", BODY),
          p("Crear o editar un equipo", H2)]
    s += steps([
        "Entra a <b>Equipos</b> (Gestión de equipos).",
        "Pulsa el botón para crear un equipo y escribe el <b>Nombre del equipo</b>.",
        "Guarda. Para cambiar el nombre más adelante, usa la opción de editar del equipo.",
    ])
    s += [p("Agregar jugadores", H2)]
    s += steps([
        "Haz clic en el equipo para abrir su detalle (<b>Integrantes del equipo</b>).",
        "Escribe el <b>nombre</b> y el <b>dorsal</b> del jugador y pulsa <b>Agregar</b>.",
        "Para corregir un dato, edita al jugador: el botón cambia a <b>Actualizar</b>.",
    ])
    s += note("Revisa que los dorsales no se repitan dentro del equipo: el anotador identifica a cada jugador por su número.",
              "Consejo", ORANGE)
    s += [p("Ficha del jugador", H2),
          p("Al abrir un jugador verás sus estadísticas de carrera y el historial de sus últimos partidos."),
          PageBreak()]

    # ── 4 ────────────────────────────────────────────────────────────────────
    s += [p("4. Crear un partido", H1),
          p("Hay dos formas de empezar, ambas desde <b>Partidos</b> o desde el panel de inicio:"),
          table([
              ["Opción", "Cuándo usarla"],
              ["Jugar ahora", "Inicia un partido en vivo con cronómetro; usa la fecha y hora actuales"],
              ["Programar partido", "Reserva una fecha para un próximo encuentro"],
          ], [4.5 * cm, 11.9 * cm]),
          p("Asistente de creación", H2)]
    s += steps([
        "<b>Equipo local</b>: elige el equipo y marca los <b>jugadores convocados</b> (de 5 a 12).",
        "Cambia a la pestaña <b>Visitante</b> y repite el proceso con el otro equipo.",
        "Completa <b>Fecha, hora y sede</b> (con \"Jugar ahora\" la fecha se llena sola).",
        "En <b>Asociar a torneo</b> elige <i>Sin torneo (Amistoso)</i> o selecciona torneo, fase y grupo.",
        "Confirma. El partido aparece en el listado de <b>Partidos</b>.",
    ])
    s += note("Si el partido pertenece a un torneo, al finalizar se actualizará la tabla de posiciones automáticamente. "
              "Un amistoso no afecta ninguna tabla.", "Torneo o amistoso")
    s += [p("Listado de partidos", H2),
          p("En <b>Partidos</b> puedes filtrar por estado (programados, en juego, finalizados) y por torneo o amistosos, "
            "y buscar por nombre. Cada tarjeta permite entrar a la mesa de control o, si ya terminó, ver el resumen."),
          PageBreak()]

    # ── 5 ────────────────────────────────────────────────────────────────────
    s += [p("5. La mesa de control (anotador)", H1),
          p("Es la pantalla para operar el partido en vivo. Pensada para usarse con rapidez: cada acción es un toque."),
          p("5.1 Antes de empezar: los titulares", H2),
          p("Si el partido aún no empieza, se abre sola una ventana por equipo para elegir los <b>5 titulares</b>."),
          ]
    s += steps([
        "Toca a los jugadores para marcarlos <b>EN CANCHA</b> (los demás quedan en <b>BANQUILLO</b>).",
        "Debes tener <b>exactamente 5</b> por equipo; el contador muestra, por ejemplo, 4 / 5.",
        "Pulsa <b>Guardar Local</b> / <b>Guardar Visitante</b>.",
    ])
    s += note("Puedes volver a abrir las ventanas con <b>Alineación Local</b> y <b>Alineación Visitante</b>, "
              "mientras el partido no haya comenzado.", "Dato")
    s += [p("5.2 Iniciar el partido", H2),
          p("Pulsa <b>INICIAR TIEMPO</b>. Si falta algún titular, la aplicación te avisa cuál equipo está incompleto. "
            "Mientras el reloj está detenido, los botones de acción de los jugadores están bloqueados."),
          p("5.3 Qué muestra la pantalla", H2),
          table([
              ["Zona", "Contenido"],
              ["Cabecera", "Volver, Deshacer, periodo actual y Finalizar Periodo"],
              ["Izquierda y derecha", "Nombre del equipo, marcador, faltas colectivas, botón Cambiar Jugador"],
              ["Centro", "Cronómetro del periodo, reloj de posesión (24 s / 14 s) y botón Iniciar/Pausar tiempo"],
              ["Abajo", "Tarjetas de los 5 jugadores en pista de cada equipo, con sus botones de acción"],
          ], [4.2 * cm, 12.2 * cm]),
          Spacer(1, 6),
          p("Cuando un equipo suma 5 faltas colectivas en el periodo aparece la etiqueta <b>BONUS</b>.")]

    s += [p("5.4 Botones de acción de cada jugador", H2),
          table([
              ["Botón", "Significa", "Efecto"],
              ["+1", "Tiro libre anotado", "Suma 1 punto"],
              ["+2", "Tiro de 2 anotado", "Suma 2 puntos"],
              ["+3", "Triple anotado", "Suma 3 puntos"],
              ["1F", "Tiro libre fallado", "Suma un intento"],
              ["2F", "Tiro de 2 fallado", "Suma un intento"],
              ["3F", "Triple fallado", "Suma un intento"],
              ["RE", "Rebote", "Suma 1 rebote"],
              ["AS", "Asistencia", "Suma 1 asistencia"],
              ["RB", "Robo", "Suma 1 robo"],
              ["FP", "Falta personal", "Suma 1 falta al jugador y al equipo"],
          ], [2.4 * cm, 5.6 * cm, 8.4 * cm]),
          Spacer(1, 6),
          p("Cada toque se guarda en el servidor. Si por algún motivo no se puede guardar (por ejemplo, el jugador "
            "no está en cancha o se perdió la conexión), la acción se revierte sola y verás un aviso en rojo."),
          p("5.5 Cinco faltas: sustitución obligatoria", H2),
          p("Cuando un jugador llega a <b>5 faltas</b> el reloj se detiene, aparece un aviso y se abre la ventana de "
            "sustitución con ese jugador ya seleccionado. Un jugador con 5 faltas no puede volver a entrar."),
          p("5.6 Cambiar un jugador", H2)]
    s += steps([
        "Pulsa <b>Cambiar Jugador</b> en el equipo que hace el cambio (el reloj se detiene).",
        "En <b>Sale (en cancha)</b> elige al jugador que sale.",
        "En <b>Entra (banquillo)</b> elige al que entra; los expulsados por faltas no aparecen.",
        "Pulsa <b>Confirmar</b>. El botón se activa solo cuando eliges a los dos.",
    ])
    s += [p("El sistema calcula automáticamente los <b>minutos jugados</b> de cada jugador con el reloj del servidor.")]

    s += [p("5.7 Deshacer una acción", H2),
          p("Pulsa <b>Deshacer</b> (o <b>Ctrl + Z</b>) para anular la última acción registrada: se corrige el marcador, "
            "las faltas y las estadísticas, y también se elimina del servidor. Puedes deshacer varias acciones seguidas, "
            "de la más reciente a la más antigua."),
          p("5.8 Fin de periodo, tiempo extra y fin del partido", H2)]
    s += bullets([
        "Cuando el cronómetro llega a 0 se abre la ventana de fin de periodo. También puedes abrirla con <b>Finalizar Periodo</b>.",
        "Periodos intermedios: pulsa <b>Avanzar al siguiente periodo</b>. Las faltas colectivas se reinician.",
        "Si al terminar el tiempo reglamentario hay <b>empate</b>, se juega un <b>tiempo extra de 5 minutos</b> "
        "(<b>Iniciar Tiempo Extra</b>); puede repetirse hasta desempatar.",
        "Si hay ganador, pulsa <b>Guardar y Ver Resumen</b>: cierra el partido, calcula minutos y actualiza la tabla del torneo.",
    ])
    s += note("El cronómetro lo controla el servidor. Si se cierra o recarga la pestaña, o cambias de dispositivo, "
              "el reloj sigue y se recupera con el tiempo correcto al volver a abrir el partido.", "Reloj seguro")
    s += [p("Consejos para anotar", H2)]
    s += bullets([
        "Usa un computador o tablet, con buena conexión, y mantén abierta una sola mesa por partido.",
        "Registra la acción en cuanto ocurre; si te equivocas, <b>Deshacer</b> al instante.",
        "Pausa el reloj en cada pausa de juego para que el tiempo de los jugadores sea exacto.",
        "Si aparece un aviso rojo, lee el mensaje: casi siempre indica que el jugador no está en cancha.",
    ])

    # ── 6 ────────────────────────────────────────────────────────────────────
    s += [p("6. Resumen del partido y exportación", H1),
          p("Al terminar un partido (o desde su tarjeta en <b>Partidos</b>, con <b>Ver resumen</b>) se abre el resumen:")]
    s += bullets([
        "<b>Marcador final</b> y puntos por periodo.",
        "<b>Box score</b> de cada equipo: minutos, puntos, rebotes, asistencias, robos, bloqueos, pérdidas y faltas.",
    ])
    s += [p("Descargar el box score", H2),
          p("Pulsa el botón <b>CSV</b> de la cabecera. Se descarga un archivo que puedes abrir en Excel o Google Sheets "
            "con todas las estadísticas de ambos equipos (incluye tiros anotados e intentados)."),
          p("Auditoría (solo administrador)", H2),
          p("El administrador ve además el botón <b>Auditoría</b>, con el historial de cada acción del partido: quién "
            "registró o deshizo un evento, quién hizo un cambio, inició o finalizó el partido, y a qué hora."),
          PageBreak()]

    # ── 7 ────────────────────────────────────────────────────────────────────
    s += [p("7. Torneos", H1),
          p("En <b>Torneos</b> ves todos los campeonatos. Al abrir uno verás sus fases, grupos, partidos y la "
            "<b>tabla de posiciones</b>."),
          p("Crear un torneo (asistente de 4 pasos)", H2)]
    s += steps([
        "<b>Configuración general</b>: nombre (obligatorio), categoría (Libre Masculino, Libre Femenino, U18 Mixto, "
        "Veteranos), formato (Fase de Grupos + Playoffs, Todos contra todos, Eliminación directa), sede y fecha de inicio.",
        "<b>Fases y grupos</b>: agrega las fases (Fase de Grupos, Eliminatoria) y sus grupos o llaves.",
        "<b>Asignación de equipos</b>: distribuye los equipos disponibles en cada grupo.",
        "<b>Resumen y confirmación</b>: revisa los datos y confirma. Todo se guarda de una sola vez.",
    ])
    s += [p("Programar partidos del torneo", H2),
          p("Dentro del detalle del torneo, elige la fase y el grupo y usa la opción de programar partido: el asistente "
            "de creación se abre ya asociado a ese grupo."),
          p("Tabla de posiciones", H2),
          table([
              ["Concepto", "Regla"],
              ["Victoria", "2 puntos de clasificación"],
              ["Derrota", "1 punto de clasificación"],
              ["Orden", "Puntos, luego diferencia de puntos anotados y recibidos, luego puntos anotados"],
              ["Actualización", "Automática al finalizar cada partido del torneo (una sola vez por partido)"],
          ], [4 * cm, 12.4 * cm]), PageBreak()]

    # ── 8 ────────────────────────────────────────────────────────────────────
    s += [p("8. Vista pública para espectadores", H1),
          p("Cualquier persona puede seguir los partidos <b>sin cuenta ni contraseña</b>:")]
    s += bullets([
        "<b>/live</b>: lista de partidos en vivo, próximos y resultados recientes.",
        "<b>/live/ID-del-partido</b>: marcador, periodo, cronómetro, faltas por equipo y estadísticas de los jugadores "
        "(los que están en cancha aparecen resaltados).",
    ])
    s += [p("La página se actualiza sola cada pocos segundos y el cronómetro avanza de forma continua. "
            "Cuando el reloj está detenido se muestra la etiqueta <b>Detenido</b>."),
          p("Cómo compartirla", H2),
          p("Comparte con el público la dirección de la aplicación seguida de <b>/live</b> (por ejemplo, en un código QR "
            "en la cancha). La pantalla de ingreso también incluye el enlace <i>Ver partidos en vivo</i>."),
          p("La vista pública es de solo lectura y no muestra datos de gestión ni de usuarios."),
          PageBreak()]

    # ── 9/10 ─────────────────────────────────────────────────────────────────
    s += [p("9. Roles y permisos", H1),
          p("Lo que puedes hacer depende del rol asignado a tu cuenta:"),
          table([
              ["Acción", "viewer", "scorer", "admin"],
              ["Ver equipos, partidos, torneos y resúmenes", "Sí", "Sí", "Sí"],
              ["Descargar box score (CSV)", "Sí", "Sí", "Sí"],
              ["Operar la mesa (titulares, reloj, acciones, deshacer, cambios, periodos, iniciar/finalizar)", "No", "Sí", "Sí"],
              ["Crear o editar equipos, jugadores, partidos y torneos", "No", "No", "Sí"],
              ["Eliminar registros", "No", "No", "Sí"],
              ["Ver la auditoría", "No", "No", "Sí"],
          ], [9.4 * cm, 2.3 * cm, 2.3 * cm, 2.4 * cm]),
          Spacer(1, 6)]
    s += note("Si intentas algo que tu rol no permite verás el mensaje <i>\"Tu rol (...) no permite esta acción\"</i>. "
              "Pide al administrador que ajuste tu rol y vuelve a iniciar sesión para que el cambio se aplique.", "Permisos")
    s += [p("Para administradores: asignar roles", H2),
          p("Los roles se asignan en Supabase (SQL Editor) escribiendo en <i>app_metadata</i> del usuario:"),
          Paragraph("<font face='Courier' size='8.5'>update auth.users set raw_app_meta_data = "
                    "coalesce(raw_app_meta_data, '{}'::jsonb) || '{\"role\":\"scorer\"}'::jsonb "
                    "where email = 'anotador@ejemplo.com';</font>",
                    ParagraphStyle("code", parent=BODY, backColor=LIGHT, borderPadding=6, leading=12, spaceBefore=4, spaceAfter=10)),
          p("Los usuarios sin rol reciben el rol por defecto que configure el administrador del sistema "
            "(por defecto, admin)."),
          PageBreak()]

    s += [p("10. Problemas frecuentes", H1),
          table([
              ["Qué pasa", "Qué hacer"],
              ["No puedo iniciar sesión", "Revisa correo y contraseña. Si persiste, pide al administrador que verifique tu cuenta."],
              ["Me devuelve al login solo", "Tu sesión caducó: vuelve a ingresar."],
              ["Los botones de los jugadores están bloqueados", "El reloj está detenido o el jugador tiene 5 faltas. Pulsa Iniciar tiempo."],
              ["Aviso rojo: el jugador no está en cancha", "Confirma los titulares y los cambios; solo se registran acciones de jugadores en cancha."],
              ["No me deja iniciar el tiempo", "Faltan titulares: cada equipo necesita exactamente 5 en cancha."],
              ["No puedo cambiar a un jugador", "El que entra no puede estar ya en cancha ni tener 5 faltas; ambos deben ser del mismo equipo."],
              ["Se cerró la pestaña en pleno partido", "Vuelve a abrir el partido: el cronómetro y las estadísticas se recuperan desde el servidor."],
              ["Dice: Tu rol no permite esta acción", "Tu cuenta es de solo lectura o de anotador. Consulta al administrador."],
              ["La primera carga tarda mucho", "El servidor puede estar \"dormido\" tras un rato sin uso; espera unos 30 segundos y reintenta."],
              ["La vista pública no muestra el partido", "Solo aparecen partidos ya creados; revisa que el número de partido sea correcto."],
          ], [6 * cm, 10.4 * cm]), Spacer(1, 12)]

    s += [p("Glosario", H2),
          table([
              ["Término", "Significado"],
              ["Box score", "Tabla con las estadísticas de cada jugador en el partido"],
              ["Bonus", "Estado de un equipo que acumuló 5 faltas colectivas en el periodo"],
              ["Dorsal", "Número de camiseta del jugador"],
              ["Convocados", "Jugadores de cada equipo que participan en un partido (5 a 12)"],
              ["Tiempo extra (OT)", "Periodo adicional de 5 minutos cuando hay empate"],
              ["Reloj de posesión", "Cuenta de 24 s (o 14 s) para atacar"],
              ["Auditoría", "Historial de quién hizo cada acción y cuándo"],
          ], [4.2 * cm, 12.2 * cm])]

    doc = Doc(OUT, pagesize=A4, title="Stats Basketball - Guía de usuario", author="Stats Basketball",
              subject="Guía de usuario", leftMargin=2.3 * cm, rightMargin=2.3 * cm)
    doc.multiBuild(s)
    return OUT


if __name__ == "__main__":
    print("PDF generado:", build())
