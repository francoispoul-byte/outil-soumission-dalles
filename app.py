import os
import zipfile
from io import BytesIO
from datetime import date, datetime, timedelta

import fitz
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet

def load_contacts_csv(filename):
    path = os.path.join(os.path.dirname(__file__), filename)

    if os.path.exists(path):
        return pd.read_csv(path).fillna("")

    return pd.DataFrame()

st.set_page_config(page_title="Calculateur de dalles quartz", layout="wide")

from datetime import datetime, timedelta


def check_password():
    SESSION_TIMEOUT_MINUTES = 60

    if "password_ok" not in st.session_state:
        st.session_state.password_ok = False

    if "last_activity" not in st.session_state:
        st.session_state.last_activity = None

    if st.session_state.password_ok:
        if st.session_state.last_activity:
            elapsed = datetime.now() - st.session_state.last_activity

            if elapsed > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                st.session_state.password_ok = False
                st.session_state.last_activity = None
                st.warning("Session expirée. Veuillez vous reconnecter.")
                st.rerun()

        st.session_state.last_activity = datetime.now()
        return True

    st.title("Les Artisans du Granit")
    st.subheader("Accès protégé")
    st.write("Veuillez entrer le mot de passe de l'entreprise.")

    password = st.text_input("Mot de passe", type="password")

    if st.button("Connexion"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.password_ok = True
            st.session_state.last_activity = datetime.now()
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")

    return False


if not check_password():
    st.stop()

if "calculated" not in st.session_state:
    st.session_state.calculated = False

st.title("Soumission & Calculateur de dalles")

project_name = st.text_input("Nom du projet", value="")

st.header("Informations soumission")

sellers_df = load_contacts_csv("vendeurs.csv")
clients_df = load_contacts_csv("clients.csv")

col_quote_1, col_quote_2 = st.columns(2)

with col_quote_1:
    st.subheader("Vendeur")

    seller_options = ["Nouveau / manuel"]
    if not sellers_df.empty and "nom" in sellers_df.columns:
        seller_options += sellers_df["nom"].astype(str).tolist()

    selected_seller = st.selectbox("Choisir un vendeur", seller_options)

    seller_default = {}
    if selected_seller != "Nouveau / manuel":
        seller_default = sellers_df[sellers_df["nom"].astype(str) == selected_seller].iloc[0].to_dict()

    seller_name = st.text_input("Nom du vendeur", value=seller_default.get("nom", ""))
    seller_phone = st.text_input("Téléphone vendeur", value=seller_default.get("telephone", ""))
    seller_email = st.text_input("Courriel vendeur", value=seller_default.get("courriel", ""))

with col_quote_2:
    st.subheader("Client")

    client_options = ["Nouveau / manuel"]
    if not clients_df.empty and "nom" in clients_df.columns:
        client_options += clients_df["nom"].astype(str).tolist()

    selected_client = st.selectbox("Choisir un client", client_options)

    client_default = {}
    if selected_client != "Nouveau / manuel":
        client_default = clients_df[clients_df["nom"].astype(str) == selected_client].iloc[0].to_dict()

    client_name = st.text_input("Nom du client", value=client_default.get("nom", ""))
    client_phone = st.text_input("Téléphone client", value=client_default.get("telephone", ""))
    client_address = st.text_input("Adresse client", value=client_default.get("adresse", ""))
    requested_by = st.text_input("Demandé par", value=client_default.get("demande_par", ""))


st.header("Coûts de production au pi²")

col1, col2, col3, col4 = st.columns(4)

with col1:
    cost_cnc = st.number_input("CNC ($/pi²)", value=5.50)
with col2:
    cost_saw = st.number_input("Scie ($/pi²)", value=1.25)
with col3:
    cost_finish = st.number_input("Finition homme ($/pi²)", value=1.25)
with col4:
    cost_install = st.number_input("Équipe installation ($/pi²)", value=7.50)

production_cost_per_sqft = cost_cnc + cost_saw + cost_finish + cost_install
st.info(f"Coût de production total : {production_cost_per_sqft:.2f} $/pi²")


st.header("Choix de dalles / couleurs")

slab_options_df = pd.DataFrame(
    [
        {"Pierre / Couleur": "Option demandée", "Largeur dalle": 126.0, "Hauteur dalle": 63.0, "Prix par dalle": 1000.0},
        {"Pierre / Couleur": "MSI Snow White 2CM", "Largeur dalle": 137.0, "Hauteur dalle": 78.0, "Prix par dalle": 725.00},
        {"Pierre / Couleur": "MSI Carrara Delphi 2CM", "Largeur dalle": 138.0, "Hauteur dalle": 79.0, "Prix par dalle": 900.0},
        {"Pierre / Couleur": "TCE 2CM", "Largeur dalle": 126.0, "Hauteur dalle": 63.0, "Prix par dalle": 500.0},
    ]
)

slab_options = st.data_editor(
    slab_options_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Pierre / Couleur": st.column_config.TextColumn("Pierre / Couleur"),
        "Largeur dalle": st.column_config.NumberColumn("Largeur dalle", min_value=1.0, step=0.125),
        "Hauteur dalle": st.column_config.NumberColumn("Hauteur dalle", min_value=1.0, step=0.125),
        "Prix par dalle": st.column_config.NumberColumn("Prix par dalle", min_value=0.0, step=50.0),
    }
)

valid_materials = [
    str(row["Pierre / Couleur"]).strip()
    for _, row in slab_options.iterrows()
    if str(row["Pierre / Couleur"]).strip()
]


st.header("Paramètres de coupe")

col_a, col_b, col_c, col_d = st.columns(4)

with col_a:
    edge_margin = st.number_input("Marge autour de la dalle (pouces)", value=0.25, step=0.25)

with col_b:
    saw_width = st.number_input("Trait de scie (pouces)", value=0.25, step=0.25)

with col_c:
    min_remnant_width = st.number_input("Largeur minimale retaille utile (pouces)", value=22.0, step=1.0)

with col_d:
    min_remnant_height = st.number_input("Hauteur minimale retaille utile (pouces)", value=22.0, step=1.0)


st.header("Paramètres de vente")

col_v1, col_v2 = st.columns(2)

with col_v1:
    base_selling_price = st.number_input("Prix de vente de base ($/pi²)", value=24.0)

with col_v2:
    minimum_profit_per_sqft = st.number_input("Profit net minimum exigé ($/pi²)", value=5.0)


st.header("Couleurs alternatives")
use_alternative_colors = st.checkbox("Créer des soumissions avec couleurs alternatives", value=False)
alternative_materials = []

if use_alternative_colors:
    col_alt_1, col_alt_2 = st.columns(2)

    with col_alt_1:
        alternative_material_1 = st.selectbox(
            "Couleur alternative 1",
            options=valid_materials,
            key="alternative_material_1"
        )
        if alternative_material_1:
            alternative_materials.append(alternative_material_1)

    with col_alt_2:
        use_second_alternative = st.checkbox("Ajouter une deuxième couleur alternative", value=False)
        if use_second_alternative:
            alternative_material_2 = st.selectbox(
                "Couleur alternative 2",
                options=valid_materials,
                key="alternative_material_2"
            )
            if alternative_material_2:
                alternative_materials.append(alternative_material_2)


st.header("Liste des morceaux")

default_material = valid_materials[0] if valid_materials else ""
second_material = default_material


def piece_editor(title_key, default_title, default_rows, editor_key):
    section_title = st.text_input(
        "Titre du tableau",
        value=default_title,
        key=title_key,
        label_visibility="collapsed"
    )

    edited = st.data_editor(
        pd.DataFrame(default_rows),
        num_rows="dynamic",
        use_container_width=True,
        key=editor_key,
        column_config={
            "Pierre / Couleur": st.column_config.SelectboxColumn("Pierre / Couleur", options=valid_materials, required=True),
            "Nom": st.column_config.TextColumn("Nom du morceau"),
            "Longueur": st.column_config.NumberColumn("Longueur", min_value=0.0, step=0.125),
            "Largeur": st.column_config.NumberColumn("Largeur", min_value=0.0, step=0.125),
            "Quantité": st.column_config.NumberColumn("Quantité", min_value=1, step=1),
            "Rotation possible": st.column_config.CheckboxColumn("Rotation possible"),
        }
    )

    return section_title, edited


section_1_title, kitchen_data = piece_editor(
    "section_1_title",
    "Cuisine",
    [
        {"Pierre / Couleur": default_material, "Nom": "Cuisine A", "Longueur": 96.0, "Largeur": 25.5, "Quantité": 1, "Rotation possible": True},
    ],
    "kitchen_editor"
)

section_2_title, island_data = piece_editor(
    "section_2_title",
    "Îlot",
    [
        {"Pierre / Couleur": default_material, "Nom": "Îlot A", "Longueur": 84.0, "Largeur": 36.0, "Quantité": 1, "Rotation possible": True},
    ],
    "island_editor"
)

section_3_title, vanity_data = piece_editor(
    "section_3_title",
    "Vanités",
    [
        {"Pierre / Couleur": second_material, "Nom": "Vanité", "Longueur": 22.0, "Largeur": 36.0, "Quantité": 1, "Rotation possible": True},
    ],
    "vanity_editor"
)


def create_slab_lookup(df):
    lookup = {}

    for _, row in df.iterrows():
        material = str(row["Pierre / Couleur"]).strip()

        if material:
            lookup[material] = {
                "stone": material,
                "width": float(row["Largeur dalle"]),
                "height": float(row["Hauteur dalle"]),
                "price": float(row["Prix par dalle"]),
            }

    return lookup


def create_piece_list(df):
    pieces = []
    piece_id = 1

    for _, row in df.iterrows():
        material = str(row["Pierre / Couleur"]).strip()
        name = str(row["Nom"]).strip()
        section = str(row["Section"]).strip() if "Section" in row else ""
        length = float(row["Longueur"])
        width = float(row["Largeur"])
        qty = int(row["Quantité"])
        rotation_possible = bool(row["Rotation possible"])

        if not material or not name or length <= 0 or width <= 0 or qty <= 0:
            continue

        for _ in range(qty):
            pieces.append({
                "id": piece_id,
                "section": section,
                "material": material,
                "name": name,
                "length": length,
                "width": width,
                "rotation_possible": rotation_possible,
                "area": length * width,
            })
            piece_id += 1

    pieces.sort(key=lambda x: x["area"], reverse=True)
    return pieces


def get_orientations(piece):
    orientations = [(piece["length"], piece["width"])]

    if piece["rotation_possible"] and piece["length"] != piece["width"]:
        orientations.append((piece["width"], piece["length"]))

    return orientations


def try_place(pieces, usable_width, usable_height, saw_width, mode="horizontal"):
    shelves = []
    placed = []
    remaining = []

    for piece in pieces:
        placed_piece = False

        for w, h in get_orientations(piece):
            if mode == "vertical":
                w, h = h, w

            if w > usable_width or h > usable_height:
                continue

            for shelf in shelves:
                if h <= shelf["height"]:
                    needed = w if shelf["used"] == 0 else w + saw_width

                    if shelf["used"] + needed <= usable_width:
                        x = shelf["used"] + (saw_width if shelf["used"] > 0 else 0)
                        y = shelf["y"]

                        placed.append({
                            **piece,
                            "x": x,
                            "y": y,
                            "w": w,
                            "h": h,
                            "shelf": shelf["index"],
                        })

                        shelf["used"] += needed
                        placed_piece = True
                        break

            if placed_piece:
                break

            used_height = 0

            if shelves:
                last = shelves[-1]
                used_height = last["y"] + last["height"] + saw_width

            if used_height + h <= usable_height:
                new_shelf = {
                    "index": len(shelves) + 1,
                    "y": used_height,
                    "height": h,
                    "used": w,
                }

                shelves.append(new_shelf)

                placed.append({
                    **piece,
                    "x": 0,
                    "y": used_height,
                    "w": w,
                    "h": h,
                    "shelf": new_shelf["index"],
                })

                placed_piece = True
                break

        if not placed_piece:
            remaining.append(piece)

    return placed, remaining, shelves


def pack_slabs(pieces, slab_width, slab_height, edge_margin, saw_width, mode):
    usable_width = slab_width - (2 * edge_margin)
    usable_height = slab_height - (2 * edge_margin)

    slabs = []
    remaining = pieces.copy()

    while remaining:
        placed, remaining_after, shelves = try_place(
            remaining,
            usable_width,
            usable_height,
            saw_width,
            mode
        )

        if not placed:
            break

        slabs.append({
            "placed": placed,
            "shelves": shelves,
            "usable_width": usable_width,
            "usable_height": usable_height,
            "slab_width": slab_width,
            "slab_height": slab_height,
        })

        remaining = remaining_after

    return slabs


def solution_is_valid(pieces, slabs):
    requested_ids = sorted([p["id"] for p in pieces])
    placed_ids = sorted([p["id"] for slab in slabs for p in slab["placed"]])

    return requested_ids == placed_ids


def solve_for_material(pieces, slab_width, slab_height, edge_margin, saw_width):
    horizontal = pack_slabs(pieces, slab_width, slab_height, edge_margin, saw_width, "horizontal")
    vertical = pack_slabs(pieces, slab_width, slab_height, edge_margin, saw_width, "vertical")

    valid_solutions = []

    if solution_is_valid(pieces, horizontal):
        valid_solutions.append({"strategy": "horizontale", "slabs": horizontal})

    if solution_is_valid(pieces, vertical):
        valid_solutions.append({"strategy": "verticale", "slabs": vertical})

    if not valid_solutions:
        return None

    valid_solutions.sort(key=lambda s: len(s["slabs"]))

    return valid_solutions[0]


def calculate_remnants(slab, min_width, min_height):
    remnants = []

    usable_width = slab["usable_width"]
    usable_height = slab["usable_height"]

    for shelf in slab["shelves"]:
        remaining_width = usable_width - shelf["used"]

        if remaining_width >= min_width and shelf["height"] >= min_height:
            remnants.append({
                "Type": "Retaille de côté",
                "Largeur": round(remaining_width, 2),
                "Hauteur": round(shelf["height"], 2),
                "Surface pi²": round((remaining_width * shelf["height"]) / 144, 2),
            })

    if slab["shelves"]:
        last_shelf = slab["shelves"][-1]
        used_height = last_shelf["y"] + last_shelf["height"]
        remaining_height = usable_height - used_height

        if remaining_height >= min_height and usable_width >= min_width:
            remnants.append({
                "Type": "Retaille du bas",
                "Largeur": round(usable_width, 2),
                "Hauteur": round(remaining_height, 2),
                "Surface pi²": round((usable_width * remaining_height) / 144, 2),
            })

    return remnants


def draw_slabs(slabs, slab_width, slab_height, edge_margin, min_width, min_height, material):
    all_remnants = []

    for idx, slab in enumerate(slabs, start=1):
        st.subheader(f"{material} — Dalle {idx}")

        fig, ax = plt.subplots(figsize=(12, 6))

        ax.add_patch(
            patches.Rectangle(
                (0, 0),
                slab_width,
                slab_height,
                fill=False,
                linewidth=2,
                edgecolor="black"
            )
        )

        ax.add_patch(
            patches.Rectangle(
                (edge_margin, edge_margin),
                slab_width - (2 * edge_margin),
                slab_height - (2 * edge_margin),
                fill=False,
                linestyle="--",
                linewidth=1,
                edgecolor="gray"
            )
        )

        for p in slab["placed"]:
            rx = p["x"] + edge_margin
            ry = p["y"] + edge_margin

            ax.add_patch(
                patches.Rectangle(
                    (rx, ry),
                    p["w"],
                    p["h"],
                    alpha=0.35
                )
            )

            label = f'{p["name"]}\n{round(p["w"], 1)} x {round(p["h"], 1)}'

            ax.text(
                rx + p["w"] / 2,
                ry + p["h"] / 2,
                label,
                ha="center",
                va="center",
                fontsize=7
            )

        for shelf in slab["shelves"]:
            y = edge_margin + shelf["y"] + shelf["height"]

            if y < slab_height - edge_margin:
                ax.plot(
                    [edge_margin, slab_width - edge_margin],
                    [y, y],
                    color="red",
                    linestyle="--",
                    linewidth=1.5
                )

        for shelf in slab["shelves"]:
            shelf_pieces = [p for p in slab["placed"] if p["shelf"] == shelf["index"]]
            shelf_pieces = sorted(shelf_pieces, key=lambda p: p["x"])

            for p in shelf_pieces[:-1]:
                x = edge_margin + p["x"] + p["w"]

                ax.plot(
                    [x, x],
                    [edge_margin + shelf["y"], edge_margin + shelf["y"] + shelf["height"]],
                    color="red",
                    linestyle="--",
                    linewidth=1.5
                )

            if shelf_pieces:
                last_piece = shelf_pieces[-1]
                x_end = edge_margin + last_piece["x"] + last_piece["w"]

                if x_end < slab_width - edge_margin:
                    ax.plot(
                        [x_end, x_end],
                        [edge_margin + shelf["y"], edge_margin + shelf["y"] + shelf["height"]],
                        color="red",
                        linestyle="--",
                        linewidth=1.5
                    )

        remnants = calculate_remnants(slab, min_width, min_height)

        for remnant in remnants:
            remnant["Pierre / Couleur"] = material
            remnant["Dalle"] = idx
            all_remnants.append(remnant)

        ax.set_xlim(0, slab_width)
        ax.set_ylim(0, slab_height)
        ax.set_aspect("equal")
        ax.grid(True)

        st.pyplot(fig)

    return all_remnants


def money(value):
    return f"{value:,.2f} $".replace(",", " ")


def clean_text(value):
    return str(value).strip() if value else ""

def safe_filename(value):
    cleaned = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in clean_text(value))
    cleaned = cleaned.strip().replace(" ", "_")
    return cleaned or "document"


def taxes_from_subtotal(subtotal):
    tps = subtotal * 0.05
    tvq = subtotal * 0.09975
    total = subtotal + tps + tvq
    return tps, tvq, total


def build_quote_pdf(
    project_name,
    seller_name,
    seller_phone,
    seller_email,
    client_name,
    client_address,
    client_phone,
    requested_by,
    section_analysis,
    total_project_sqft,
    total_sales
):
    template_path = os.path.join(os.path.dirname(__file__), "template_soumission.pdf")

    tps, tvq, total_with_tax = taxes_from_subtotal(total_sales)

    final_buffer = BytesIO()
    final_canvas = canvas.Canvas(final_buffer, pagesize=letter)

    template_doc = fitz.open(template_path)
    page = template_doc[0]
    pix = page.get_pixmap(dpi=200)

    img_path = os.path.join(os.path.dirname(__file__), "temp_template.png")
    pix.save(img_path)

    final_canvas.drawImage(
        img_path,
        0,
        0,
        width=letter[0],
        height=letter[1]
    )

    final_canvas.setFont("Helvetica", 9)

    # vendeur
    final_canvas.drawRightString(556, 668, clean_text(seller_name))
    final_canvas.drawRightString(556, 654, clean_text(seller_phone))
    final_canvas.drawRightString(556, 640, clean_text(seller_email))

    # client
    final_canvas.drawString(53, 595, clean_text(client_name))
    final_canvas.drawString(53, 581, clean_text(client_address))
    final_canvas.drawString(53, 567, clean_text(client_phone))
    final_canvas.drawString(53, 553, clean_text(requested_by))

    # date
    final_canvas.drawString(510, 595, str(date.today()))

    # projet
    final_canvas.drawString(465, 560, clean_text(project_name))

    # lignes tableau
    row_y_positions = [487, 470, 453]

    for i, (section_name, values) in enumerate(section_analysis.items()):
        pc = values["PC"]
        vente = values["Vente"]

        couleurs = ", ".join(sorted(values.get("Couleurs", [])))
        description = f"{section_name} - {couleurs}" if couleurs else section_name

        y = row_y_positions[i] if i < len(row_y_positions) else row_y_positions[-1] - ((i - 2) * 22)

        final_canvas.drawCentredString(105, y, f"{pc:.2f}")
        final_canvas.drawCentredString(300, y, description)
        final_canvas.drawRightString(545, y, money(vente))

    # totaux
    final_canvas.drawRightString(545, 295, money(total_sales))
    final_canvas.drawRightString(545, 277, money(tps))
    final_canvas.drawRightString(545, 259, money(tvq))
    final_canvas.drawRightString(545, 242, money(total_with_tax))

    final_canvas.save()
    final_buffer.seek(0)

    return final_buffer


def create_slab_figure(slab, slab_width, slab_height, edge_margin, material, slab_index):
    fig, ax = plt.subplots(figsize=(10, 5))

    ax.add_patch(
        patches.Rectangle(
            (0, 0),
            slab_width,
            slab_height,
            fill=False,
            linewidth=2,
            edgecolor="black"
        )
    )

    ax.add_patch(
        patches.Rectangle(
            (edge_margin, edge_margin),
            slab_width - (2 * edge_margin),
            slab_height - (2 * edge_margin),
            fill=False,
            linestyle="--",
            linewidth=1,
            edgecolor="gray"
        )
    )

    for p in slab["placed"]:
        rx = p["x"] + edge_margin
        ry = p["y"] + edge_margin

        ax.add_patch(
            patches.Rectangle(
                (rx, ry),
                p["w"],
                p["h"],
                alpha=0.35
            )
        )

        label = f'{p["name"]}\n{round(p["w"], 1)} x {round(p["h"], 1)}'

        ax.text(
            rx + p["w"] / 2,
            ry + p["h"] / 2,
            label,
            ha="center",
            va="center",
            fontsize=7
        )

    for shelf in slab["shelves"]:
        y = edge_margin + shelf["y"] + shelf["height"]

        if y < slab_height - edge_margin:
            ax.plot(
                [edge_margin, slab_width - edge_margin],
                [y, y],
                color="red",
                linestyle="--",
                linewidth=1.5
            )

    for shelf in slab["shelves"]:
        shelf_pieces = [p for p in slab["placed"] if p["shelf"] == shelf["index"]]
        shelf_pieces = sorted(shelf_pieces, key=lambda p: p["x"])

        for p in shelf_pieces[:-1]:
            x = edge_margin + p["x"] + p["w"]

            ax.plot(
                [x, x],
                [edge_margin + shelf["y"], edge_margin + shelf["y"] + shelf["height"]],
                color="red",
                linestyle="--",
                linewidth=1.5
            )

        if shelf_pieces:
            last_piece = shelf_pieces[-1]
            x_end = edge_margin + last_piece["x"] + last_piece["w"]

            if x_end < slab_width - edge_margin:
                ax.plot(
                    [x_end, x_end],
                    [edge_margin + shelf["y"], edge_margin + shelf["y"] + shelf["height"]],
                    color="red",
                    linestyle="--",
                    linewidth=1.5
                )

    ax.set_title(f"{material} — Dalle {slab_index}")
    ax.set_xlim(0, slab_width)
    ax.set_ylim(0, slab_height)
    ax.set_aspect("equal")
    ax.grid(True)

    img_buffer = BytesIO()
    fig.savefig(img_buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    img_buffer.seek(0)
    return img_buffer


def build_production_pdf(project_name, slab_display_data):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>PDF PRODUCTION - PLANS DE COUPE</b>", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Projet :</b> {clean_text(project_name)}", styles["Normal"]))
    story.append(Paragraph(f"<b>Date :</b> {date.today()}", styles["Normal"]))
    story.append(Spacer(1, 16))

    for item in slab_display_data:
        material = item["material"]
        selected = item["selected"]
        strategy = item["strategy"]
        slab_count = item["slab_count"]
        slab_width_value = item["slab_width_value"]
        slab_height_value = item["slab_height_value"]

        story.append(Paragraph(f"<b>Pierre / Couleur : {material}</b>", styles["Heading2"]))
        story.append(Paragraph(f"Stratégie : {strategy} - Nombre de dalles : {slab_count}", styles["Normal"]))
        story.append(Spacer(1, 10))

        for idx, slab in enumerate(selected, start=1):
            story.append(Paragraph(f"<b>{material} — Dalle {idx}</b>", styles["Heading3"]))

            img_buffer = create_slab_figure(
                slab=slab,
                slab_width=slab_width_value,
                slab_height=slab_height_value,
                edge_margin=edge_margin,
                material=material,
                slab_index=idx
            )

            slab_image = Image(
                img_buffer,
                width=9.2 * inch,
                height=4.6 * inch
            )

            story.append(slab_image)
            story.append(Spacer(1, 8))

            rows = [["Morceau", "Longueur", "Largeur", "X", "Y", "Rotation"]]

            for p in slab["placed"]:
                rows.append([
                    p["name"],
                    f"{p['w']:.2f}",
                    f"{p['h']:.2f}",
                    f"{p['x']:.2f}",
                    f"{p['y']:.2f}",
                    "Oui" if p["rotation_possible"] else "Non",
                ])

            table = Table(
                rows,
                colWidths=[
                    2.2 * inch,
                    1.1 * inch,
                    1.1 * inch,
                    1.0 * inch,
                    1.0 * inch,
                    1.0 * inch
                ]
            )

            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]))

            story.append(table)
            story.append(PageBreak())

    doc.build(story)
    buffer.seek(0)

    return buffer


def calculate_quote_data(
    all_pieces_df,
    slab_options,
    production_cost_per_sqft,
    base_selling_price,
    minimum_profit_per_sqft,
    edge_margin,
    saw_width
):
    slab_lookup = create_slab_lookup(slab_options)
    pieces = create_piece_list(all_pieces_df)

    if not pieces:
        return None

    materials = sorted(set([p["material"] for p in pieces]))

    section_analysis = {}
    material_rows = []
    sales_rows = []
    slab_display_data = []

    total_project_sqft = 0
    total_slabs = 0
    total_slab_cost = 0
    total_fabrication_cost = 0
    total_sales = 0
    total_slab_surface_sqft = 0

    for material in materials:
        if material not in slab_lookup:
            raise ValueError(f"La pierre / couleur '{material}' n'existe pas dans les choix de dalles.")

        slab_info = slab_lookup[material]
        stone_name = slab_info["stone"]
        slab_width_value = slab_info["width"]
        slab_height_value = slab_info["height"]
        slab_price = slab_info["price"]

        material_pieces = [p for p in pieces if p["material"] == material]

        result = solve_for_material(
            material_pieces,
            slab_width_value,
            slab_height_value,
            edge_margin,
            saw_width
        )

        if result is None:
            raise ValueError(f"Aucune solution valide trouvée pour : {material}")

        selected = result["slabs"]
        strategy = result["strategy"]

        slab_count = len(selected)
        project_sqft = sum(p["area"] for p in material_pieces) / 144
        slab_surface_sqft = (slab_width_value * slab_height_value / 144) * slab_count
        slab_cost_total = slab_count * slab_price
        fabrication_cost = project_sqft * production_cost_per_sqft
        real_total_cost = fabrication_cost + slab_cost_total

        normal_sale_per_sqft = base_selling_price
        normal_sale_total = normal_sale_per_sqft * project_sqft
        normal_profit = normal_sale_total - real_total_cost
        normal_profit_per_sqft = normal_profit / project_sqft if project_sqft > 0 else 0

        if normal_profit_per_sqft < minimum_profit_per_sqft:
            required_sale_total = real_total_cost + (minimum_profit_per_sqft * project_sqft)
            final_sale_per_sqft = required_sale_total / project_sqft
        else:
            final_sale_per_sqft = normal_sale_per_sqft

        sale_total = final_sale_per_sqft * project_sqft
        profit = sale_total - real_total_cost
        profit_per_sqft = profit / project_sqft if project_sqft > 0 else 0
        sale_adjustment = final_sale_per_sqft - normal_sale_per_sqft

        for section_name in sorted(set([p["section"] for p in material_pieces])):
            section_pieces = [p for p in material_pieces if p["section"] == section_name]
            section_sqft = sum(p["area"] for p in section_pieces) / 144
            section_ratio = section_sqft / project_sqft if project_sqft > 0 else 0

            section_fabrication_cost = section_sqft * production_cost_per_sqft
            section_slab_cost = slab_cost_total * section_ratio
            section_total_cost = section_fabrication_cost + section_slab_cost
            section_sale_total = section_sqft * final_sale_per_sqft
            section_profit = section_sale_total - section_total_cost

            if section_name not in section_analysis:
                section_analysis[section_name] = {
                    "PC": 0,
                    "Vente": 0,
                    "Fabrication": 0,
                    "Dalles": 0,
                    "Coût total": 0,
                    "Profit": 0,
                    "Couleurs": set(),
                }

            section_analysis[section_name]["PC"] += section_sqft
            section_analysis[section_name]["Vente"] += section_sale_total
            section_analysis[section_name]["Fabrication"] += section_fabrication_cost
            section_analysis[section_name]["Dalles"] += section_slab_cost
            section_analysis[section_name]["Coût total"] += section_total_cost
            section_analysis[section_name]["Profit"] += section_profit
            section_analysis[section_name]["Couleurs"].update([p["material"] for p in section_pieces])

        total_project_sqft += project_sqft
        total_slabs += slab_count
        total_slab_cost += slab_cost_total
        total_fabrication_cost += fabrication_cost
        total_sales += sale_total
        total_slab_surface_sqft += slab_surface_sqft

        gross_loss_sqft = slab_surface_sqft - project_sqft
        gross_loss_percent = (gross_loss_sqft / slab_surface_sqft) * 100 if slab_surface_sqft > 0 else 0

        material_rows.append({
            "Pierre / Couleur": stone_name,
            "Prix dalle": f"{slab_price:,.2f} $",
            "PC du projet": round(project_sqft, 2),
            "NBR Dalle": slab_count,
            "PC dalles achetées": round(slab_surface_sqft, 2),
            "PC perte brute": round(gross_loss_sqft, 2),
            "% perte brute": f"{gross_loss_percent:.2f} %",
            "Coût dalles total": f"{slab_cost_total:,.2f} $",
        })

        sales_rows.append({
            "Pierre / Couleur": stone_name,
            "PC projet": round(project_sqft, 2),
            "Coût fabrication": f"{fabrication_cost:,.2f} $",
            "Coût dalles": f"{slab_cost_total:,.2f} $",
            "Coût total réel": f"{real_total_cost:,.2f} $",
            "Prix vente initial / PC": f"{normal_sale_per_sqft:.2f} $",
            "Profit initial / PC": f"{normal_profit_per_sqft:.2f} $",
            "Ajustement / PC": f"{sale_adjustment:.2f} $",
            "Prix vente final / PC": f"{final_sale_per_sqft:.2f} $",
            "Prix total projet": f"{sale_total:,.2f} $",
            "Profit final": f"{profit:,.2f} $",
            "Profit final / PC": f"{profit_per_sqft:.2f} $",
        })

        slab_display_data.append({
            "material": material,
            "selected": selected,
            "slab_width_value": slab_width_value,
            "slab_height_value": slab_height_value,
            "strategy": strategy,
            "slab_count": slab_count,
        })

    total_cost = total_fabrication_cost + total_slab_cost
    final_profit = total_sales - total_cost
    final_profit_per_sqft = final_profit / total_project_sqft if total_project_sqft > 0 else 0

    return {
        "pieces": pieces,
        "materials": materials,
        "material_rows": material_rows,
        "sales_rows": sales_rows,
        "section_analysis": section_analysis,
        "slab_display_data": slab_display_data,
        "total_project_sqft": total_project_sqft,
        "total_slabs": total_slabs,
        "total_slab_cost": total_slab_cost,
        "total_fabrication_cost": total_fabrication_cost,
        "total_sales": total_sales,
        "total_slab_surface_sqft": total_slab_surface_sqft,
        "total_cost": total_cost,
        "final_profit": final_profit,
        "final_profit_per_sqft": final_profit_per_sqft,
    }


def make_alternative_pieces_df(all_pieces_df, material_name):
    alt_df = all_pieces_df.copy()
    alt_df["Pierre / Couleur"] = material_name
    return alt_df


def build_comparison_pdf(project_name, comparison_rows, client_name="", client_address="", client_phone="", requested_by=""):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=28,
        bottomMargin=28
    )

    styles = getSampleStyleSheet()
    story = []

    # Logo à partir du template existant
    template_path = os.path.join(os.path.dirname(__file__), "template_soumission.pdf")
    logo_path = os.path.join(os.path.dirname(__file__), "logo_temp.png")

    try:
        template_doc = fitz.open(template_path)
        page = template_doc[0]

        # Zone approximative du logo dans le PDF template
        logo_clip = fitz.Rect(35, 45, 220, 150)
        pix = page.get_pixmap(clip=logo_clip, dpi=200)
        pix.save(logo_path)

        story.append(Image(logo_path, width=2.3 * inch, height=1.15 * inch))
    except Exception:
        pass

    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>COMPARATIF DES OPTIONS</b>", styles["Title"]))
    story.append(Spacer(1, 12))

    info_data = [
        ["Projet :", clean_text(project_name)],
        ["Client :", clean_text(client_name)],
        ["Adresse :", clean_text(client_address)],
        ["Téléphone :", clean_text(client_phone)],
        ["Demandé par :", clean_text(requested_by)],
        ["Date :", str(date.today())],
    ]

    info_table = Table(info_data, colWidths=[1.4 * inch, 5.3 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(info_table)
    story.append(Spacer(1, 18))

    table_data = [[
        "Option",
        "Prix avant taxes",
        "Total avec taxes",
        "Différence $",
        "Différence %"
    ]]

    for row in comparison_rows:
        table_data.append([
            row["label"],
            money(row["subtotal"]) if isinstance(row["subtotal"], (int, float)) else row["subtotal"],
            money(row["total_with_tax"]) if isinstance(row["total_with_tax"], (int, float)) else row["total_with_tax"],
            row["difference_display"],
            row["difference_percent_display"],
        ])

    comparison_table = Table(
        table_data,
        colWidths=[
            2.2 * inch,
            1.35 * inch,
            1.35 * inch,
            1.2 * inch,
            1.0 * inch,
        ]
    )

    comparison_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(comparison_table)
    story.append(Spacer(1, 18))

    story.append(Paragraph(
        "Les différences sont calculées en comparaison avec l’option principale.",
        styles["Normal"]
    ))

    doc.build(story)
    buffer.seek(0)

    return buffer

def create_section_rows(section_analysis):
    rows = []

    for section_name, values in section_analysis.items():
        pc = values["PC"]
        profit_pc = values["Profit"] / pc if pc > 0 else 0
        vente_pc = values["Vente"] / pc if pc > 0 else 0

        rows.append({
            "Section": section_name,
            "PC": round(pc, 2),
            "Vente totale": money(values["Vente"]),
            "Vente / PC": f"{vente_pc:.2f} $",
            "Coût fabrication": money(values["Fabrication"]),
            "Coût dalles attribué": money(values["Dalles"]),
            "Coût total": money(values["Coût total"]),
            "Profit": money(values["Profit"]),
            "Profit / PC": f"{profit_pc:.2f} $",
        })

    return rows


def create_analysis_rows(data):
    total_project_sqft = data["total_project_sqft"]
    total_sales = data["total_sales"]
    total_fabrication_cost = data["total_fabrication_cost"]
    total_slab_cost = data["total_slab_cost"]

    total_cost = total_fabrication_cost + total_slab_cost
    final_profit = total_sales - total_cost
    final_profit_per_sqft = final_profit / total_project_sqft if total_project_sqft > 0 else 0

    return [
        {
            "Analyse": "Vente totale",
            "Valeur": money(total_sales),
            "PC": f"{(total_sales / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Coût fabrication",
            "Valeur": money(total_fabrication_cost),
            "PC": f"{production_cost_per_sqft:.2f} $/pi²"
        },
        {
            "Analyse": "Coût dalles",
            "Valeur": money(total_slab_cost),
            "PC": f"{(total_slab_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Coût total",
            "Valeur": money(total_cost),
            "PC": f"{(total_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Profit net",
            "Valeur": money(final_profit),
            "PC": f"{final_profit_per_sqft:.2f} $/pi²"
        },
    ]

def build_sales_analysis_pdf(project_name, quote_items):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24
    )

    styles = getSampleStyleSheet()
    story = []

    for index, item in enumerate(quote_items, start=1):
        label = item["label"]
        material_rows = item.get("material_rows", [])
        sales_rows = item.get("sales_rows", [])
        section_rows = item.get("section_rows", [])
        analysis_rows = item.get("analysis_rows", [])

        story.append(Paragraph(f"<b>ANALYSE DE LA VENTE</b>", styles["Title"]))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>Projet :</b> {clean_text(project_name)}", styles["Normal"]))
        story.append(Paragraph(f"<b>Option :</b> {clean_text(label)}", styles["Normal"]))
        story.append(Paragraph(f"<b>Date :</b> {date.today()}", styles["Normal"]))
        story.append(Spacer(1, 12))

        def add_table(title, rows):
            story.append(Paragraph(f"<b>{title}</b>", styles["Heading2"]))
            story.append(Spacer(1, 6))

            if not rows:
                story.append(Paragraph("Aucune donnée.", styles["Normal"]))
                story.append(Spacer(1, 10))
                return

            headers = list(rows[0].keys())
            table_data = [headers]

            for row in rows:
                table_data.append([str(row.get(h, "")) for h in headers])

            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("PADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))

            story.append(table)
            story.append(Spacer(1, 12))

        add_table("Matière", material_rows)
        add_table("Vente", sales_rows)
        add_table("Analyse de vente par section", section_rows)
        add_table("Analyse du prix", analysis_rows)

        if index < len(quote_items):
            story.append(PageBreak())

    doc.build(story)
    buffer.seek(0)

    return buffer

def build_quote_zip(project_name, quote_items, comparison_rows):
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for index, item in enumerate(quote_items, start=1):
            pdf_buffer = build_quote_pdf(
                project_name=project_name,
                seller_name=item["seller_name"],
                seller_phone=item["seller_phone"],
                seller_email=item["seller_email"],
                client_name=item["client_name"],
                client_address=item["client_address"],
                client_phone=item["client_phone"],
                requested_by=item["requested_by"],
                section_analysis=item["section_analysis"],
                total_project_sqft=item["total_project_sqft"],
                total_sales=item["total_sales"],
            )

            safe_project = safe_filename(project_name)
            safe_client = safe_filename(item["client_name"])
            safe_color = safe_filename(item["label"])

            filename = f"Soumission_{safe_project}_{safe_color}_{safe_client}.pdf"
            zip_file.writestr(filename, pdf_buffer.getvalue())
            production_pdf_buffer = build_production_pdf(
                project_name=project_name,
                slab_display_data=item["slab_display_data"]
            )

            production_filename = f"Production_{safe_project}_{safe_color}_{safe_client}.pdf"
            zip_file.writestr(production_filename, production_pdf_buffer.getvalue())

        comparison_pdf = build_comparison_pdf(
            project_name=project_name,
            comparison_rows=comparison_rows,
            client_name=quote_items[0]["client_name"] if quote_items else "",
            client_address=quote_items[0]["client_address"] if quote_items else "",
            client_phone=quote_items[0]["client_phone"] if quote_items else "",
            requested_by=quote_items[0]["requested_by"] if quote_items else "",
            )
        
        safe_project = safe_filename(project_name)
        safe_client = safe_filename(quote_items[0]["client_name"]) if quote_items else "client"
        
        sales_analysis_pdf = build_sales_analysis_pdf(project_name, quote_items)

        zip_file.writestr(
            f"Analyse_vente_{safe_project}_{safe_client}.pdf",
            sales_analysis_pdf.getvalue()
        )


        zip_file.writestr(
            f"Comparatif_{safe_project}_{safe_client}.pdf",
            comparison_pdf.getvalue()
        )

    zip_buffer.seek(0)
    return zip_buffer

if st.button("Calculer"):
    st.session_state.calculated = True

if st.session_state.calculated:
    kitchen_calc = kitchen_data.copy()
    kitchen_calc["Section"] = section_1_title

    island_calc = island_data.copy()
    island_calc["Section"] = section_2_title

    vanity_calc = vanity_data.copy()
    vanity_calc["Section"] = section_3_title

    all_pieces_df = pd.concat(
        [kitchen_calc, island_calc, vanity_calc],
        ignore_index=True
    )

    try:
        quote_data = calculate_quote_data(
            all_pieces_df,
            slab_options,
            production_cost_per_sqft,
            base_selling_price,
            minimum_profit_per_sqft,
            edge_margin,
            saw_width
        )
    except ValueError as error:
        st.error(str(error))
        st.stop()

    if quote_data is None:
        st.error("Aucun morceau valide à calculer.")
        st.stop()

    pieces = quote_data["pieces"]
    materials = quote_data["materials"]
    all_material_rows = quote_data["material_rows"]
    all_sales_rows = quote_data["sales_rows"]
    slab_display_data = quote_data["slab_display_data"]
    section_analysis = quote_data["section_analysis"]

    total_project_sqft = quote_data["total_project_sqft"]
    total_slabs = quote_data["total_slabs"]
    total_slab_cost = quote_data["total_slab_cost"]
    total_fabrication_cost = quote_data["total_fabrication_cost"]
    total_sales = quote_data["total_sales"]
    total_slab_surface_sqft = quote_data["total_slab_surface_sqft"]
    total_cost = quote_data["total_cost"]
    final_profit = quote_data["final_profit"]
    final_profit_per_sqft = quote_data["final_profit_per_sqft"]

    all_remnants = []

    st.success(f"Projet : {project_name}")

    client_summary = []

    if client_name.strip():
        client_summary.append(f"Client : {client_name}")

    if client_address.strip():
        client_summary.append(f"Adresse : {client_address}")

    if client_phone.strip():
        client_summary.append(f"Téléphone : {client_phone}")

    if requested_by.strip():
        client_summary.append(f"Demandé par : {requested_by}")

    if client_summary:
        st.info(" | ".join(client_summary))

    st.header("Matière")
    st.dataframe(pd.DataFrame(all_material_rows), use_container_width=True)

    st.header("Vente")
    st.dataframe(pd.DataFrame(all_sales_rows), use_container_width=True)

    st.header("Analyse de vente par section")

    section_rows = []

    for section_name, values in section_analysis.items():
        pc = values["PC"]
        profit_pc = values["Profit"] / pc if pc > 0 else 0
        vente_pc = values["Vente"] / pc if pc > 0 else 0

        section_rows.append({
            "Section": section_name,
            "PC": round(pc, 2),
            "Vente totale": f"{values['Vente']:,.2f} $",
            "Vente / PC": f"{vente_pc:.2f} $",
            "Coût fabrication": f"{values['Fabrication']:,.2f} $",
            "Coût dalles attribué": f"{values['Dalles']:,.2f} $",
            "Coût total": f"{values['Coût total']:,.2f} $",
            "Profit": f"{values['Profit']:,.2f} $",
            "Profit / PC": f"{profit_pc:.2f} $",
        })

    st.dataframe(pd.DataFrame(section_rows), use_container_width=True)

    st.header("Analyse du prix")

    analysis_df = pd.DataFrame(
        [
            {
                "Analyse": "Vente totale",
                "Valeur": f"{total_sales:,.2f} $",
                "PC": f"{(total_sales / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
            },
            {
                "Analyse": "Coût fabrication",
                "Valeur": f"{total_fabrication_cost:,.2f} $",
                "PC": f"{production_cost_per_sqft:.2f} $/pi²"
            },
            {
                "Analyse": "Coût dalles",
                "Valeur": f"{total_slab_cost:,.2f} $",
                "PC": f"{(total_slab_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
            },
            {
                "Analyse": "Coût total",
                "Valeur": f"{total_cost:,.2f} $",
                "PC": f"{(total_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
            },
            {
                "Analyse": "Profit net",
                "Valeur": f"{final_profit:,.2f} $",
                "PC": f"{final_profit_per_sqft:.2f} $/pi²"
            },
        ]
    )

    st.table(analysis_df)

    if final_profit_per_sqft < minimum_profit_per_sqft:
        st.error("Le profit minimum n'est pas atteint.")
    else:
        st.success(f"Profit minimum atteint : {final_profit_per_sqft:.2f} $/pi²")

    gross_loss_total = total_slab_surface_sqft - total_project_sqft
    gross_loss_percent_total = (gross_loss_total / total_slab_surface_sqft) * 100 if total_slab_surface_sqft > 0 else 0

    st.header("Analyse des pertes / retailles")

    loss_df = pd.DataFrame(
        [
            {"Analyse": "Surface totale des dalles achetées", "Valeur": f"{total_slab_surface_sqft:,.2f} pi²"},
            {"Analyse": "Surface utilisée projet", "Valeur": f"{total_project_sqft:,.2f} pi²"},
            {"Analyse": "Surface perdue brute", "Valeur": f"{gross_loss_total:,.2f} pi²"},
            {"Analyse": "% perte brute", "Valeur": f"{gross_loss_percent_total:.2f} %"},
        ]
    )

    st.table(loss_df)

    st.header("PDF")

    quote_items = []
    comparison_rows = []

    _, _, principal_total_with_tax = taxes_from_subtotal(total_sales)

    quote_items.append({
        "label": "soumission_principale",
        "seller_name": seller_name,
        "seller_phone": seller_phone,
        "seller_email": seller_email,
        "client_name": client_name,
        "client_address": client_address,
        "client_phone": client_phone,
        "requested_by": requested_by,
        "section_analysis": section_analysis,
        "total_project_sqft": total_project_sqft,
        "total_sales": total_sales,
        "slab_display_data": slab_display_data,
        "material_rows": all_material_rows,
        "sales_rows": all_sales_rows,
        "section_rows": section_rows,
        "analysis_rows": analysis_df.to_dict("records"),
    })

    comparison_rows.append({
        "label": "Option principale",
        "subtotal": total_sales,
        "total_with_tax": principal_total_with_tax,
        "difference_display": "-",
        "difference_percent_display": "-",
    })

    alternative_materials_unique = []
    for material_name in alternative_materials:
        if material_name and material_name not in alternative_materials_unique:
            alternative_materials_unique.append(material_name)

    for alt_index, material_name in enumerate(alternative_materials_unique, start=1):
        try:
            alt_pieces_df = make_alternative_pieces_df(all_pieces_df, material_name)
            alt_data = calculate_quote_data(
                alt_pieces_df,
                slab_options,
                production_cost_per_sqft,
                base_selling_price,
                minimum_profit_per_sqft,
                edge_margin,
                saw_width
            )

            alt_label = f"alternative_{alt_index}_{safe_filename(material_name)}"
            _, _, alt_total_with_tax = taxes_from_subtotal(alt_data["total_sales"])
            difference = alt_total_with_tax - principal_total_with_tax
            difference_percent = (difference / principal_total_with_tax) * 100 if principal_total_with_tax > 0 else 0

            quote_items.append({
                "label": alt_label,
                "seller_name": seller_name,
                "seller_phone": seller_phone,
                "seller_email": seller_email,
                "client_name": client_name,
                "client_address": client_address,
                "client_phone": client_phone,
                "requested_by": requested_by,
                "section_analysis": alt_data["section_analysis"],
                "total_project_sqft": alt_data["total_project_sqft"],
                "total_sales": alt_data["total_sales"],
                "slab_display_data": alt_data["slab_display_data"],
                "material_rows": alt_data["material_rows"],
                "sales_rows": alt_data["sales_rows"],
                "section_rows": create_section_rows(alt_data["section_analysis"]),
                "analysis_rows": create_analysis_rows(alt_data),
            })

            comparison_rows.append({
                "label": material_name,
                "subtotal": alt_data["total_sales"],
                "total_with_tax": alt_total_with_tax,
                "difference_display": f"{difference:+,.2f} $".replace(",", " "),
                "difference_percent_display": f"{difference_percent:+.2f} %",
            })

        except ValueError as error:
            st.error(str(error))

    quote_zip = build_quote_zip(project_name, quote_items, comparison_rows)

    st.download_button(
        label="Télécharger dossier complet (.zip)",
        data=quote_zip,
        file_name=f"dossier_soumissions_{safe_filename(project_name)}.zip",
        mime="application/zip"
    )

    st.header("Plans de coupe par dalle")

    for item in slab_display_data:
        st.header(f"Pierre / Couleur : {item['material']}")
        st.success(
            f"Meilleure stratégie validée : {item['strategy']} "
            f"({item['slab_count']} dalles)"
        )

        all_remnants.extend(
            draw_slabs(
                item["selected"],
                item["slab_width_value"],
                item["slab_height_value"],
                edge_margin,
                min_remnant_width,
                min_remnant_height,
                item["material"]
            )
        )

    st.header("Retailles restantes utiles")

    if all_remnants:
        remnant_df = pd.DataFrame(all_remnants)
        remnant_df = remnant_df[["Pierre / Couleur", "Dalle", "Type", "Largeur", "Hauteur", "Surface pi²"]]

        useful_remnants_sqft = remnant_df["Surface pi²"].sum()
        net_loss_sqft = gross_loss_total - useful_remnants_sqft

        st.dataframe(remnant_df, use_container_width=True)
        st.info(f"Total des retailles utiles : {useful_remnants_sqft:.2f} pi²")
        st.info(f"Perte nette après retailles utiles : {net_loss_sqft:.2f} pi²")
    else:
        st.warning("Aucune retaille utile selon les dimensions minimales indiquées.")
