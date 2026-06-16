import os
import zipfile
import math
from io import BytesIO
from datetime import date
from collections import OrderedDict

import fitz
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet
from pricing_config import PRICING_CONFIG


def looks_like_percent(value):
    if pd.isna(value) or value == "":
        return False

    try:
        float(str(value).replace("%", "").replace(",", ".").strip())
        return True
    except ValueError:
        return False


def normalize_clients_df(df):
    expected_columns = [
        "nom",
        "telephone",
        "adresse",
        "demande_par",
        "rabais_client",
        "commission_designer",
    ]

    for column in expected_columns:
        if column not in df.columns:
            df[column] = ""
        else:
            df[column] = df[column].astype(object)

    # Corrige les anciennes lignes sans virgule vide pour demande_par :
    # adresse,5,0 devient demande_par="", rabais_client=5, commission_designer=0.
    shifted_rows = (
        df["commission_designer"].astype(str).str.strip().eq("")
        & df["demande_par"].apply(looks_like_percent)
        & df["rabais_client"].apply(looks_like_percent)
    )

    df.loc[shifted_rows, "commission_designer"] = df.loc[shifted_rows, "rabais_client"]
    df.loc[shifted_rows, "rabais_client"] = df.loc[shifted_rows, "demande_par"]
    df.loc[shifted_rows, "demande_par"] = ""

    return df


def load_contacts_csv(filename):
    path = os.path.join(os.path.dirname(__file__), filename)

    if os.path.exists(path):
        contacts_df = pd.read_csv(path).fillna("")

        if filename == "clients.csv":
            contacts_df = normalize_clients_df(contacts_df)

        return contacts_df

    return pd.DataFrame()


def money(value):
    return f"{value:,.2f} $".replace(",", " ")


def clean_percent(value):
    if pd.isna(value) or value == "":
        return None

    try:
        return float(str(value).replace("%", "").replace(",", ".").strip())
    except ValueError:
        return None


def get_seller_commission_pct(seller_default, type_projet, pricing):
    if not seller_default:
        return float(pricing["commission_vente_pct"] * 100)

    commission_column = (
        "commission_residentiel"
        if type_projet == "Résidentiel"
        else "commission_multilogement"
    )

    seller_commission = clean_percent(seller_default.get(commission_column, ""))

    if seller_commission is None:
        return float(pricing["commission_vente_pct"] * 100)

    return seller_commission


def get_client_percent_default(client_default, column_name, fallback=0.0):
    if not client_default:
        return fallback

    client_percent = clean_percent(client_default.get(column_name, ""))

    if client_percent is None:
        return fallback

    return client_percent

BASE_DIR = Path(__file__).parent

@st.cache_data
def charger_catalogues():
    catalogue = pd.read_excel(BASE_DIR / "catalogue_groupes.xlsx")

    catalogue.columns = (
        catalogue.columns
        .str.strip()
        .str.replace("Builder", "builder", regex=False)
    )

    return catalogue

st.set_page_config(page_title="Calculateur de dalles quartz", layout="wide")

SESSION_TIMEOUT_SECONDS = 60 * 60

def check_password():
    import time

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if "login_time" not in st.session_state:
        st.session_state.login_time = None

    if st.session_state.authenticated:
        elapsed = time.time() - st.session_state.login_time

        if elapsed > SESSION_TIMEOUT_SECONDS:
            st.session_state.authenticated = False
            st.session_state.login_time = None
            st.warning("Session expirée. Veuillez vous reconnecter.")
            st.stop()

        return True

    st.title("Connexion")
    password = st.text_input("Mot de passe", type="password")

    if st.button("Se connecter"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.session_state.login_time = time.time()
            st.rerun()
        else:
            st.error("Mot de passe invalide.")

    return False

if not check_password():
    st.stop()

if "calculated" not in st.session_state:
    st.session_state.calculated = False

st.title("Soumission & Calculateur de dalles")

catalogue_groupes = charger_catalogues()

project_name = st.text_input("Nom du projet", value="")

project_date = st.date_input(
    "Date prévue du projet",
    value=date.today()
)

st.header("Type de soumission")

type_projet = st.radio(
    "Sélectionne le type de projet",
    ["Résidentiel", "Multilogement"],
    horizontal=True
)

if type_projet == "Multilogement":
    unit_count = st.number_input(
        "Nombre d'unités",
        min_value=1,
        value=1,
        step=1
    )
else:
    unit_count = 1

if type_projet == "R\u00e9sidentiel":
    type_materiau = st.radio(
        "S\u00e9lectionne le type de mat\u00e9riau",
        ["Quartz / Granit", "Dekton / Porcelaine"],
        horizontal=True
    )
else:
    type_materiau = "Quartz / Granit"

pricing = PRICING_CONFIG[type_projet]["materiaux"][type_materiau]
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

sales_commission_default_pct = get_seller_commission_pct(
    seller_default,
    type_projet,
    pricing
)

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
    if type_projet == "R\u00e9sidentiel":
        client_discount_default_pct = get_client_percent_default(client_default, "rabais_client", 0.0)
        client_discount_pct = st.number_input(
            "Rabais client (%)",
            min_value=0.0,
            max_value=10.0,
            value=float(client_discount_default_pct),
            step=0.5,
            key=f"client_discount_{selected_client}"
        ) / 100
    else:
        client_discount_pct = 0.0


st.header("Co\u00fbts de production au pi\u00b2")

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    cost_cnc = st.number_input("CNC ($/pi\u00b2)", value=float(pricing["couts_pc"]["cnc"]), step=0.25)

with col2:
    cost_saw = st.number_input("Scie ($/pi\u00b2)", value=float(pricing["couts_pc"]["scie"]), step=0.25)

with col3:
    cost_finish = st.number_input("Finition homme ($/pi\u00b2)", value=float(pricing["couts_pc"]["finition"]), step=0.25)

with col4:
    cost_install = st.number_input("\u00c9quipe installation ($/pi\u00b2)", value=float(pricing["couts_pc"]["installation"]), step=0.25)

with col5:
    if type_projet == "Multilogement":
        measurement_cost_per_unit = st.number_input(
            "Prise de mesure ($/unit\u00e9)",
            value=80.0,
            step=5.0
        )
        measurement_cost = unit_count * measurement_cost_per_unit
    else:
        measurement_cost = st.number_input(
            "Prise de mesure ($/projet)",
            value=float(pricing["mesure_projet"]),
            step=25.0
        )

with col6:
    sales_commission_pct = st.number_input(
        "Commission vente (%)",
        value=float(sales_commission_default_pct),
        step=0.25,
        key=f"sales_commission_{selected_seller}_{type_projet}"
    ) / 100

production_cost_per_sqft = cost_cnc + cost_saw + cost_finish + cost_install

st.info(f"Co\u00fbt de production total : {production_cost_per_sqft:.2f} $/pi\u00b2")

if type_projet == "Multilogement":
    st.info(
        f"Prise de mesure totale : {unit_count} unit\u00e9s \u00d7 "
        f"{measurement_cost_per_unit:.2f} $ = {money(measurement_cost)}"
    )

st.header("Choix de dalles / couleurs")

def clean_price(value):
    if pd.isna(value) or value == "":
        return None

    if isinstance(value, str):
        value = (
            value.replace("$", "")
            .replace(" ", "")
            .replace(",", ".")
            .strip()
        )

    try:
        return float(value)
    except ValueError:
        return None

def get_slab_from_catalogue(
    fournisseur,
    couleur,
    epaisseur,
    type_projet,
    longueur_choisie=None,
    largeur_choisie=None
):
    ligne = catalogue_groupes[
        (catalogue_groupes["Fournisseur"] == fournisseur) &
        (catalogue_groupes["Couleur"] == couleur)
    ]

    if longueur_choisie is not None and largeur_choisie is not None:
        ligne = ligne[
            (ligne["Longueur"].astype(float) == float(longueur_choisie)) &
            (ligne["Largeur"].astype(float) == float(largeur_choisie))
        ]

    if ligne.empty:
        return None

    row = ligne.iloc[0]

    surface_pc = (float(row["Longueur"]) * float(row["Largeur"])) / 144

    if type_projet == "Multilogement":
        prix_dalle_col = f"Prix builder {epaisseur} dalle"
        prix_pc_col = f"Prix builder {epaisseur} / PC"
    else:
        prix_dalle_col = f"Prix normal {epaisseur} dalle"
        prix_pc_col = f"Prix normal {epaisseur} / PC"

    prix_dalle = clean_price(row.get(prix_dalle_col))

    if prix_dalle is None:
        prix_pc = clean_price(row.get(prix_pc_col))

        if prix_pc is None:
            return None

        prix_dalle = prix_pc * surface_pc

    return {
        "Pierre / Couleur": f"{fournisseur} | {couleur} | {epaisseur}",
        "Largeur dalle": float(row["Longueur"]),
        "Hauteur dalle": float(row["Largeur"]),
        "Prix par dalle": float(prix_dalle),
    }


nb_couleurs = st.radio(
    "Nombre de couleurs pour le projet",
    [1, 2, 3, 4, 5, 6],
    horizontal=True
)

selected_slabs = []

for i in range(1, nb_couleurs + 1):
    st.subheader(f"Couleur {i}")

    mode_couleur = st.radio(
        f"Mode couleur {i}",
        ["Catalogue Excel", "Manuel"],
        horizontal=True,
        key=f"mode_couleur_{i}"
    )

    if mode_couleur == "Catalogue Excel":
        col_c1, col_c2, col_c3 = st.columns(3)

        with col_c1:
            fournisseurs = sorted(catalogue_groupes["Fournisseur"].dropna().unique())
            fournisseur = st.selectbox(
                f"Fournisseur couleur {i}",
                [""] + fournisseurs,
                key=f"fournisseur_{i}"
            )

        if fournisseur:
            couleurs_filtrees = catalogue_groupes[
                catalogue_groupes["Fournisseur"] == fournisseur
            ].copy()

            couleurs_filtrees["Option couleur"] = (
                couleurs_filtrees["Couleur"].astype(str)
                + " | "
                + couleurs_filtrees["Longueur"].astype(str)
                + " x "
                + couleurs_filtrees["Largeur"].astype(str)
            )

            couleurs_disponibles = sorted(
                couleurs_filtrees["Option couleur"]
                .dropna()
                .unique()
            )

        else:
            couleurs_disponibles = []

        with col_c2:
            couleur = st.selectbox(
                f"Couleur {i}",
                [""] + couleurs_disponibles,
                key=f"couleur_{i}"
            )
        couleur_nom = couleur.split(" | ")[0] if couleur else ""

        dimension_choisie = couleur.split(" | ")[1] if couleur and " | " in couleur else ""
        longueur_choisie = float(dimension_choisie.split(" x ")[0]) if dimension_choisie else None
        largeur_choisie = float(dimension_choisie.split(" x ")[1]) if dimension_choisie else None

        epaisseurs_disponibles = []

        for epaisseur_test in ["2CM", "3CM"]:
            test_slab = get_slab_from_catalogue(
                fournisseur=fournisseur,
                couleur=couleur_nom,
                epaisseur=epaisseur_test,
                type_projet=type_projet,
                longueur_choisie=longueur_choisie,
                largeur_choisie=largeur_choisie
            )

            if test_slab:
                epaisseurs_disponibles.append(epaisseur_test)

        with col_c3:
            if epaisseurs_disponibles:
                epaisseur = st.selectbox(
                    f"Épaisseur {i}",
                    epaisseurs_disponibles,
                    key=f"epaisseur_{i}"
                )
            else:
                epaisseur = None
                st.selectbox(
                    f"Épaisseur {i}",
                    ["Non disponible"],
                    disabled=True,
                    key=f"epaisseur_{i}"
                )

        if fournisseur and couleur and epaisseur:
            slab_info = get_slab_from_catalogue(
                fournisseur=fournisseur,
                couleur=couleur_nom,
                epaisseur=epaisseur,
                type_projet=type_projet,
                longueur_choisie=longueur_choisie,
                largeur_choisie=largeur_choisie
            )

            if slab_info:
                selected_slabs.append(slab_info)

                surface_dalle_pc = (
                slab_info["Largeur dalle"] * slab_info["Hauteur dalle"]
                ) / 144

                prix_matiere_pc = slab_info["Prix par dalle"] / surface_dalle_pc

                st.info(
                    f"Format dalle : {slab_info['Largeur dalle']:.0f} x {slab_info['Hauteur dalle']:.0f} po | "
                    f"Surface : {surface_dalle_pc:.2f} pi² | "
                    f"Prix dalle : {slab_info['Prix par dalle']:.2f} $ | "
                    f"Prix matière : {prix_matiere_pc:.2f} $/pi²"
                )
            else:
                st.error("Prix introuvable dans le catalogue.")

    else:
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)

        with col_m1:
            manual_material = st.text_input(
                f"Nom couleur manuelle {i}",
                key=f"manual_material_{i}"
            )

        with col_m2:
            manual_width = st.number_input(
                f"Longueur dalle manuelle {i}",
                min_value=1.0,
                step=0.125,
                value=126.0,
                key=f"manual_width_{i}"
            )

        with col_m3:
            manual_height = st.number_input(
                f"Largeur dalle manuelle {i}",
                min_value=1.0,
                step=0.125,
                value=63.0,
                key=f"manual_height_{i}"
            )

        with col_m4:
            manual_price = st.number_input(
                f"Prix dalle manuel {i}",
                min_value=0.0,
                step=50.0,
                value=1000.0,
                key=f"manual_price_{i}"
            )

        if manual_material.strip():
            selected_slabs.append({
                "Pierre / Couleur": manual_material.strip(),
                "Largeur dalle": float(manual_width),
                "Hauteur dalle": float(manual_height),
                "Prix par dalle": float(manual_price),
            })

            st.success(
                f"{manual_material.strip()} | "
                f"{manual_width} x {manual_height} | "
                f"{manual_price:.2f} $"
            )

slab_options = pd.DataFrame(selected_slabs)

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

col_v1, col_v2, col_v3, col_v4 = st.columns(4)

with col_v1:
    base_selling_price = st.number_input(
        "Prix de vente de base ($/pi²)",
        value=float(pricing["prix_base_pc"]),
        step=1.0
    )

with col_v2:
    minimum_profit_per_sqft = st.number_input(
        "Profit net minimum exigé ($/pi²)",
        value=float(pricing["profit_net_min_pc"]),
        step=1.0
    )

with col_v3:
    material_margin_pct = st.number_input(
        "Marge sur matière (%)",
        value=float(pricing["marge_matiere_pct"] * 100),
        step=1.0
    ) / 100

with col_v4:
    designer_commission_default_pct = get_client_percent_default(
        client_default,
        "commission_designer",
        0.0
    )
    designer_commission_pct = st.number_input(
        "Commission designer (%)",
        min_value=0.0,
        max_value=30.0,
        value=float(designer_commission_default_pct),
        step=0.5,
        key=f"designer_commission_{selected_client}"
    ) / 100

if type_projet == "Résidentiel":

    st.subheader("Options")

    col_opt1, col_opt2 = st.columns(2)

    with col_opt1:
        laminage = st.checkbox("Laminer")
        laminage_pl = st.number_input(
            "Pieds linéaires laminer",
            min_value=0.0,
            step=0.5,
            value=0.0,
            disabled=not laminage
        )

    with col_opt2:
        og = st.checkbox("OG")
        og_pl = st.number_input(
            "Pieds linéaires OG",
            min_value=0.0,
            step=0.5,
            value=0.0,
            disabled=not og
        )
else:
    laminage = False
    og = False
    laminage_pl = 0
    og_pl = 0

if laminage:
    quote_profile_text = "Profil : carr\u00e9 et lamin\u00e9"
elif og:
    quote_profile_text = "Profil : OG"
else:
    quote_profile_text = "Profil : carr\u00e9"

st.header("Texte inclus dans la soumission")
st.text(quote_profile_text)

quote_sink_cut_text = st.text_input(
    "D\u00e9coupe pour \u00e9vier et robinet",
    value="D\u00e9coupe pour \u00e9vier et robinet incluse"
)
quote_measurement_install_text = st.text_input(
    "Prise de mesure, livraison et installation",
    value="Prise de mesure, livraison et installation incluses"
)
quote_exclusions_text = st.text_input(
    "Exclusions",
    value="Exclusions : robinet et \u00e9vier"
)
project_note = st.text_input(
    "Note à afficher sur la soumission",
    value="",
    placeholder="Ex. Attention : délais plus long pour cette couleur"
)

st.header("Couleurs alternatives")

alternative_materials = []

if len(valid_materials) <= 1:
    st.info("Ajoute au moins 2 couleurs dans les choix de dalles pour créer un comparatif.")
else:
    use_alternative_colors = st.checkbox(
        "Créer des soumissions avec couleurs alternatives",
        value=False
    )

    if use_alternative_colors:
        nb_alternatives = st.number_input(
            "Nombre de couleurs alternatives",
            min_value=1,
            max_value=min(5, len(valid_materials)),
            value=1,
            step=1
        )

        for alt_index in range(1, int(nb_alternatives) + 1):
            alternative_material = st.selectbox(
                f"Couleur alternative {alt_index}",
                options=[""] + valid_materials,
                key=f"alternative_material_{alt_index}"
            )

            if alternative_material:
                alternative_materials.append(alternative_material)

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

section_4_title, section_4_data = piece_editor(
    "section_4_title",
    "Section 4",
    [
        {"Pierre / Couleur": default_material, "Nom": "", "Longueur": 0.0, "Largeur": 0.0, "Quantité": 1, "Rotation possible": True},
    ],
    "section_4_editor"
)

section_5_title, section_5_data = piece_editor(
    "section_5_title",
    "Section 5",
    [
        {"Pierre / Couleur": default_material, "Nom": "", "Longueur": 0.0, "Largeur": 0.0, "Quantité": 1, "Rotation possible": True},
    ],
    "section_5_editor"
)

piece_sections = [
    (section_1_title, kitchen_data),
    (section_2_title, island_data),
    (section_3_title, vanity_data),
    (section_4_title, section_4_data),
    (section_5_title, section_5_data),
]


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


def first_existing_column(df, names):
    for name in names:
        if name in df.columns:
            return name

    return None


def piece_can_fit(piece, usable_width, usable_height):
    return any(w <= usable_width and h <= usable_height for w, h in get_orientations(piece))


def split_oversized_piece(piece, slab_width, slab_height, edge_margin):
    usable_width = slab_width - (2 * edge_margin)
    usable_height = slab_height - (2 * edge_margin)

    if usable_width <= 0 or usable_height <= 0:
        raise ValueError("La dalle utile est invalide. Vérifie la marge autour de la dalle.")

    if piece_can_fit(piece, usable_width, usable_height):
        return [piece], []

    max_part_length = max(usable_width, usable_height) if piece["rotation_possible"] else usable_width
    max_part_width = max(usable_width, usable_height) if piece["rotation_possible"] else usable_height

    if piece["length"] >= piece["width"]:
        split_axis = "length"
        max_dimension = max_part_length
    else:
        split_axis = "width"
        max_dimension = max_part_width

    if max_dimension <= 0:
        raise ValueError(f"Impossible de couper automatiquement le morceau '{piece['name']}' : dimension utile invalide.")

    part_count = max(2, math.ceil(piece[split_axis] / max_dimension))
    parts = []
    split_rows = []

    for part_index in range(1, part_count + 1):
        part = piece.copy()
        part["id"] = f"{piece['id']}-{part_index}"
        part["name"] = f"{piece['name']} - partie {part_index}"
        part["original_id"] = piece.get("original_id", piece["id"])
        part["original_name"] = piece.get("original_name", piece["name"])
        part["original_length"] = piece.get("original_length", piece["length"])
        part["original_width"] = piece.get("original_width", piece["width"])
        part["split_part"] = part_index
        part["split_total"] = part_count

        if split_axis == "length":
            part["length"] = piece["length"] / part_count
        else:
            part["width"] = piece["width"] / part_count

        part["area"] = part["length"] * part["width"]

        if not piece_can_fit(part, usable_width, usable_height):
            raise ValueError(
                f"Impossible de couper automatiquement le morceau '{piece['name']}' "
                f"pour la dalle utile {usable_width:.2f} x {usable_height:.2f}."
            )

        parts.append(part)
        split_rows.append({
            "Pierre / Couleur": piece["material"],
            "Nom original": piece["name"],
            "Dimension originale": f"{piece['length']:.2f} x {piece['width']:.2f}",
            "Partie": f"partie {part_index}",
            "Dimension partie": f"{part['length']:.2f} x {part['width']:.2f}",
        })

    original_area = piece["length"] * piece["width"]
    split_area = sum(part["area"] for part in parts)

    if abs(original_area - split_area) > 0.001:
        raise ValueError(f"Erreur de coupe automatique pour '{piece['name']}' : la surface n'est pas conservée.")

    return parts, split_rows


def split_oversized_pieces_for_material(pieces, slab_width, slab_height, edge_margin):
    prepared_pieces = []
    split_rows = []

    for piece in pieces:
        parts, piece_split_rows = split_oversized_piece(piece, slab_width, slab_height, edge_margin)
        prepared_pieces.extend(parts)
        split_rows.extend(piece_split_rows)

    prepared_pieces.sort(key=lambda x: x["area"], reverse=True)
    return prepared_pieces, split_rows


def create_requested_summary(all_pieces_df):
    qty_col = first_existing_column(all_pieces_df, ["Quantité", "QuantitÃ©"])
    rotation_col = first_existing_column(all_pieces_df, ["Rotation possible"])
    grouped = OrderedDict()

    for _, row in all_pieces_df.iterrows():
        section = str(row.get("Section", "")).strip()
        material = str(row.get("Pierre / Couleur", "")).strip()
        name = str(row.get("Nom", "")).strip()
        length = float(row.get("Longueur", 0) or 0)
        width = float(row.get("Largeur", 0) or 0)
        rotation_possible = bool(row.get(rotation_col, False)) if rotation_col else False
        qty = int(row.get(qty_col, 0) or 0) if qty_col else 0

        if not material or not name or length <= 0 or width <= 0 or qty <= 0:
            continue

        key = (section, material, name, round(length, 3), round(width, 3), rotation_possible)

        if key not in grouped:
            grouped[key] = {
                "Section": section,
                "Pierre / Couleur": material,
                "Nom": name,
                "Longueur": round(length, 2),
                "Largeur": round(width, 2),
                "Rotation possible": "Oui" if rotation_possible else "Non",
                "Quantité demandée": 0,
            }

        grouped[key]["Quantité demandée"] += qty

    return list(grouped.values())


def create_placed_summary(slab_display_data):
    grouped = OrderedDict()

    for item in slab_display_data:
        material = item["material"]

        for slab in item["selected"]:
            for piece in slab["placed"]:
                # La validation utilise le morceau original pour ne pas compter chaque partie comme une quantite demandee.
                original_id = piece.get("original_id", piece.get("id"))
                name = piece.get("original_name", piece.get("name", ""))
                length = float(piece.get("original_length", piece.get("length", piece.get("w", 0))))
                width = float(piece.get("original_width", piece.get("width", piece.get("h", 0))))
                key = (material, name, round(length, 3), round(width, 3))

                if key not in grouped:
                    grouped[key] = {
                        "Pierre / Couleur": material,
                        "Nom": name,
                        "Longueur": round(length, 2),
                        "Largeur": round(width, 2),
                        "Quantité répartie": 0,
                        "_original_ids": set(),
                    }

                if original_id not in grouped[key]["_original_ids"]:
                    grouped[key]["_original_ids"].add(original_id)
                    grouped[key]["Quantité répartie"] += 1

    rows = list(grouped.values())
    for row in rows:
        row.pop("_original_ids", None)

    return rows

def create_validation_summary(requested_rows, placed_rows):
    requested = OrderedDict()
    placed = OrderedDict()

    for row in requested_rows:
        key = (
            row["Pierre / Couleur"],
            row["Nom"],
            round(float(row["Longueur"]), 3),
            round(float(row["Largeur"]), 3),
        )
        requested[key] = requested.get(key, 0) + int(row.get("Quantité demandée", row.get("Quantit\u00c3\u00a9 demand\u00c3\u00a9e", 0)))

    for row in placed_rows:
        key = (
            row["Pierre / Couleur"],
            row["Nom"],
            round(float(row["Longueur"]), 3),
            round(float(row["Largeur"]), 3),
        )
        placed[key] = placed.get(key, 0) + int(row.get("Quantité répartie", row.get("Quantit\u00c3\u00a9 r\u00c3\u00a9partie", 0)))

    validation_rows = []

    for key in sorted(set(requested) | set(placed)):
        requested_qty = requested.get(key, 0)
        placed_qty = placed.get(key, 0)
        validation_rows.append({
            "Pierre / Couleur": key[0],
            "Nom": key[1],
            "Longueur": round(key[2], 2),
            "Largeur": round(key[3], 2),
            "Quantité demandée": requested_qty,
            "Quantité répartie": placed_qty,
            "Écart": placed_qty - requested_qty,
        })

    return validation_rows


def validation_is_successful(validation_rows):
    return all(int(row.get("Écart", 0)) == 0 for row in validation_rows)


def slab_signature(slab):
    placed_signature = []

    for piece in slab["placed"]:
        placed_signature.append((
            piece.get("name", ""),
            round(float(piece.get("x", 0)), 3),
            round(float(piece.get("y", 0)), 3),
            round(float(piece.get("w", 0)), 3),
            round(float(piece.get("h", 0)), 3),
        ))

    return tuple(sorted(placed_signature))


def compress_slabs_by_cut(selected_slabs):
    compressed = OrderedDict()

    for slab_index, slab in enumerate(selected_slabs, start=1):
        signature = slab_signature(slab)

        if signature not in compressed:
            compressed[signature] = {
                "slab": slab,
                "quantity": 0,
                "slab_indexes": [],
            }

        compressed[signature]["quantity"] += 1
        compressed[signature]["slab_indexes"].append(slab_index)

    return list(compressed.values())


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
    requested_ids = sorted([str(p["id"]) for p in pieces])
    placed_ids = sorted([str(p["id"]) for slab in slabs for p in slab["placed"]])

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
        # Affichage Streamlit désactivé : les plans de coupe restent générés seulement dans le PDF Production.
        remnants = calculate_remnants(slab, min_width, min_height)

        for remnant in remnants:
            remnant["Pierre / Couleur"] = material
            remnant["Dalle"] = idx
            all_remnants.append(remnant)

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
    project_date,
    project_note,
    quote_profile_text,
    quote_sink_cut_text,
    quote_measurement_install_text,
    quote_exclusions_text,
    seller_name,
    seller_phone,
    seller_email,
    client_name,
    client_address,
    client_phone,
    requested_by,
    section_analysis,
    total_project_sqft,
    total_sales,
    client_discount_pct=0,
    client_discount_amount=0,
    laminage=False,
    laminage_pl=0,
    og=False,
    og_pl=0
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
    final_canvas.drawRightString(556, 632, clean_text(seller_name))
    final_canvas.drawRightString(556, 618, clean_text(seller_phone))
    final_canvas.drawRightString(556, 604, clean_text(seller_email))

    # client
    final_canvas.drawString(53, 553, clean_text(client_name))
    final_canvas.drawString(53, 539, clean_text(client_address))
    final_canvas.drawString(53, 525, clean_text(client_phone))
    final_canvas.drawString(53, 511, clean_text(requested_by))

    # date
    final_canvas.drawCentredString(
        505,
        555,
        str(date.today())
    )

    # projet
    final_canvas.drawCentredString(
        505,
        524,
        clean_text(project_name)
    )
    final_canvas.drawCentredString(
        505,
        510,
        f"Date prévue : {project_date.strftime('%Y-%m-%d')}"
    )

    # lignes tableau
    section_start_y = 452
    section_line_spacing = 17
    last_section_y = section_start_y

    for i, (section_name, values) in enumerate(section_analysis.items()):
        pc = values["PC"]
        vente = values["Vente"]

        couleurs = ", ".join(sorted(values.get("Couleurs", [])))
        description = f"{section_name} - {couleurs}" if couleurs else section_name

        y = section_start_y - (i * section_line_spacing)
        last_section_y = y

        final_canvas.drawCentredString(105, y, f"{pc:.2f}")
        final_canvas.drawCentredString(300, y, description)
        final_canvas.drawRightString(545, y, money(vente))
    
    if client_discount_amount > 0:
        rabais_y = min(383, last_section_y - 17)
        final_canvas.drawCentredString(300, rabais_y, f"Rabais -{client_discount_pct * 100:.1f} %")
        final_canvas.drawRightString(545, rabais_y, f"-{money(client_discount_amount)}")
    
        option_start_y = rabais_y - 17
    else:
        option_start_y = min(366, last_section_y - 17)

    if clean_text(project_note):
        final_canvas.setFont("Helvetica-Bold", 10)
        final_canvas.drawString(
            52,
            259,
            f"*** {clean_text(project_note)} ***"
        )
        final_canvas.setFont("Helvetica", 10)

    quote_included_lines = [
        quote_profile_text,
        quote_sink_cut_text,
        quote_measurement_install_text,
        quote_exclusions_text,
    ]
    quote_included_lines = [clean_text(line) for line in quote_included_lines if clean_text(line)]

    if quote_included_lines:
        final_canvas.setFont("Helvetica", 9)

        included_text_x = 180
        included_text_y = 332
        included_line_spacing = 17

        for index, line in enumerate(quote_included_lines):
            final_canvas.drawCentredString(
                300,
                included_text_y - (index * included_line_spacing),
                line
            )

    # options

    if laminage and laminage_pl > 0:
        final_canvas.drawCentredString(
            300,
            option_start_y,
            f"Laminer : {laminage_pl:.1f} pieds linéaires"
        )
        option_start_y -= 17

    if og and og_pl > 0:
        final_canvas.drawCentredString(
            300,
            option_start_y,
            f"OG : {og_pl:.1f} pieds linéaires"
        )

    # totaux
    final_canvas.drawRightString(545, 264, money(total_sales))
    final_canvas.drawRightString(545, 247, money(tps))
    final_canvas.drawRightString(545, 230, money(tvq))
    final_canvas.drawRightString(545, 213, money(total_with_tax))

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


def build_production_pdf(project_name, project_date, slab_display_data, requested_rows, placed_rows, validation_rows, split_piece_rows=None):
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

    def add_pdf_table(title, rows, validation_table=False):
        story.append(Paragraph(f"<b>{title}</b>", styles["Heading2"]))
        story.append(Spacer(1, 4))

        if not rows:
            story.append(Paragraph("Aucune donnée.", styles["Normal"]))
            story.append(Spacer(1, 8))
            return

        headers = list(rows[0].keys())
        table_data = [headers]
        table_data.extend([[str(row.get(header, "")) for header in headers] for row in rows])

        table = Table(table_data, repeatRows=1)
        style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("PADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]

        if validation_table and "Écart" in headers:
            ecart_col = headers.index("Écart")
            for row_index, row in enumerate(rows, start=1):
                if int(row.get("Écart", 0)) != 0:
                    style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.mistyrose))
                    style_commands.append(("TEXTCOLOR", (ecart_col, row_index), (ecart_col, row_index), colors.red))

        table.setStyle(TableStyle(style_commands))
        story.append(table)
        story.append(Spacer(1, 10))

    story.append(Paragraph("<b>PDF PRODUCTION - PLANS DE COUPE</b>", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<b>Projet :</b> {clean_text(project_name)} &nbsp;&nbsp;&nbsp; "
        f"<b>Date prévue :</b> {project_date.strftime('%Y-%m-%d')} &nbsp;&nbsp;&nbsp; "
        f"<b>Date :</b> {date.today()}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 10))

    add_pdf_table("Tableau demandé", requested_rows)
    add_pdf_table("Tableau regroupé / réparti", placed_rows)
    add_pdf_table("Validation des quantités", validation_rows, validation_table=True)

    add_pdf_table("Morceaux coupés automatiquement", split_piece_rows)

    if validation_is_successful(validation_rows):
        story.append(Paragraph("<b>Validation réussie : toutes les quantités concordent.</b>", styles["Normal"]))
    else:
        story.append(Paragraph("<b>Attention : des écarts de quantités sont présents.</b>", styles["Normal"]))

    story.append(PageBreak())

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

        compressed_slabs = compress_slabs_by_cut(selected)

        for idx, compressed in enumerate(compressed_slabs, start=1):
            slab = compressed["slab"]
            quantity = compressed["quantity"]

            story.append(Paragraph(f"<b>Plan type {idx}</b>", styles["Heading3"]))
            story.append(Paragraph(f"<b>Quantité de cette coupe : {quantity} fois</b>", styles["Normal"]))

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
            2.8 * inch,
                    1.1 * inch,
                    1.1 * inch,
            0.85 * inch,
            0.85 * inch,
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
    material_margin_pct,
    measurement_cost,
    sales_commission_pct,
    designer_commission_pct,
    client_discount_pct,
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
    total_sales_before_discount = 0
    total_slab_surface_sqft = 0
    total_measurement_cost = 0
    total_sales_commission = 0
    total_designer_commission = 0
    total_client_discount = 0
    split_piece_rows = []

    for material in materials:
        if material not in slab_lookup:
            raise ValueError(f"La pierre / couleur '{material}' n'existe pas dans les choix de dalles.")

        slab_info = slab_lookup[material]
        stone_name = slab_info["stone"]
        slab_width_value = slab_info["width"]
        slab_height_value = slab_info["height"]
        slab_price = slab_info["price"]

        material_pieces = [p for p in pieces if p["material"] == material]
        material_pieces, material_split_rows = split_oversized_pieces_for_material(
            material_pieces,
            slab_width_value,
            slab_height_value,
            edge_margin
        )
        split_piece_rows.extend(material_split_rows)

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

        slab_sqft = (slab_width_value * slab_height_value) / 144
        slab_cost_per_sqft = slab_price / slab_sqft if slab_sqft > 0 else 0

        slab_surface_sqft = slab_sqft * slab_count
        slab_cost_total = slab_count * slab_price

        fabrication_cost = project_sqft * production_cost_per_sqft

        material_sale_per_sqft = slab_cost_per_sqft * (1 + material_margin_pct)

        normal_sale_per_sqft = base_selling_price + material_sale_per_sqft
        normal_sale_total = normal_sale_per_sqft * project_sqft

        commission_rate = sales_commission_pct
        sales_commission = normal_sale_total * commission_rate

        real_total_cost = (
            fabrication_cost
            + slab_cost_total
            + measurement_cost
            + sales_commission
        )

        normal_profit = normal_sale_total - real_total_cost
        normal_profit_per_sqft = normal_profit / project_sqft if project_sqft > 0 else 0

        fixed_cost_before_commission = (
            fabrication_cost
            + slab_cost_total
            + measurement_cost
        )

        minimum_profit_total = minimum_profit_per_sqft * project_sqft

        minimum_sale_total_required = (
            fixed_cost_before_commission + minimum_profit_total
        ) / (1 - commission_rate)

        if normal_sale_total < minimum_sale_total_required:
            sale_total = minimum_sale_total_required
            final_sale_per_sqft = sale_total / project_sqft
        else:
            sale_total = normal_sale_total
            final_sale_per_sqft = normal_sale_per_sqft
        laminage_total = laminage_pl * 20 if laminage else 0
        og_total = og_pl * 20 if og else 0

        sale_total_avant_commission_designer = sale_total + laminage_total + og_total
        designer_commission_amount = sale_total_avant_commission_designer * designer_commission_pct

        sale_total_avant_rabais = sale_total_avant_commission_designer + designer_commission_amount
        client_discount_amount = sale_total_avant_rabais * client_discount_pct

        sale_total = sale_total_avant_rabais - client_discount_amount
        final_sale_per_sqft = sale_total / project_sqft if project_sqft > 0 else 0

        sales_commission = sale_total * commission_rate

        real_total_cost = (
            fixed_cost_before_commission
            + sales_commission
            + designer_commission_amount
        )

        profit = sale_total - real_total_cost
        profit_per_sqft = profit / project_sqft if project_sqft > 0 else 0
        sale_adjustment = final_sale_per_sqft - normal_sale_per_sqft

        for section_name in sorted(set([p["section"] for p in material_pieces])):
            section_pieces = [p for p in material_pieces if p["section"] == section_name]
            section_sqft = sum(p["area"] for p in section_pieces) / 144
            section_ratio = section_sqft / project_sqft if project_sqft > 0 else 0

            section_base_fabrication_cost = section_sqft * production_cost_per_sqft
            section_measurement_cost = measurement_cost * section_ratio
            section_sales_commission = sales_commission * section_ratio
            section_designer_commission = designer_commission_amount * section_ratio
            section_client_discount = client_discount_amount * section_ratio

            section_fabrication_cost = section_base_fabrication_cost

            section_slab_cost = slab_cost_total * section_ratio

            section_total_cost = (
                section_fabrication_cost
                + section_measurement_cost
                + section_slab_cost
                + section_sales_commission
                + section_designer_commission
            )

            section_sale_total = section_sqft * final_sale_per_sqft
            section_profit = section_sale_total - section_total_cost

            if section_name not in section_analysis:
                section_analysis[section_name] = {
                    "PC": 0,
                    "Vente": 0,
                    "Fabrication": 0,
                    "Mesure": 0,
                    "Dalles": 0,
                    "Commission vendeur": 0,
                    "Commission designer": 0,
                    "Rabais client": 0,
                    "Coût total": 0,
                    "Profit": 0,
                    "Couleurs": set(),
                }

            section_analysis[section_name]["PC"] += section_sqft
            section_analysis[section_name]["Vente"] += section_sale_total
            section_analysis[section_name]["Fabrication"] += section_fabrication_cost
            section_analysis[section_name]["Mesure"] += section_measurement_cost
            section_analysis[section_name]["Dalles"] += section_slab_cost
            section_analysis[section_name]["Commission vendeur"] += section_sales_commission
            section_analysis[section_name]["Commission designer"] += section_designer_commission
            section_analysis[section_name]["Rabais client"] += section_client_discount
            section_analysis[section_name]["Coût total"] += section_total_cost
            section_analysis[section_name]["Profit"] += section_profit
            section_analysis[section_name]["Couleurs"].update([p["material"] for p in section_pieces])

        total_project_sqft += project_sqft
        total_slabs += slab_count
        total_slab_cost += slab_cost_total
        total_fabrication_cost += fabrication_cost
        total_measurement_cost += measurement_cost
        total_sales_commission += sales_commission
        total_designer_commission += designer_commission_amount
        total_client_discount += client_discount_amount
        total_sales_before_discount += sale_total_avant_rabais
        total_sales += sale_total
        total_slab_surface_sqft += slab_surface_sqft

        gross_loss_sqft = slab_surface_sqft - project_sqft
        gross_loss_percent = (gross_loss_sqft / slab_surface_sqft) * 100 if slab_surface_sqft > 0 else 0

        material_rows.append({
            "Pierre / Couleur": stone_name,
            "Dimension dalle": f"{slab_width_value:.0f} x {slab_height_value:.0f}",
            "Prix dalle": money(slab_price),
            "Prix matière / PC": f"{slab_cost_per_sqft:.2f} $",
            "PC du projet": round(project_sqft, 2),
            "NBR Dalle": slab_count,
            "PC dalles achetées": round(slab_surface_sqft, 2),
            "PC perte brute": round(gross_loss_sqft, 2),
            "% perte brute": f"{gross_loss_percent:.2f} %",
            "Coût dalles total": money(slab_cost_total),
        })

        sales_rows.append({
            "Pierre / Couleur": stone_name,
            "PC projet": round(project_sqft, 2),
            "Coût fabrication": money(fabrication_cost + measurement_cost + sales_commission),
            "Coût dalles": money(slab_cost_total),
            "Coût total réel": money(real_total_cost),
            "Prix vente initial / PC": f"{normal_sale_per_sqft:.2f} $",
            "Profit initial / PC": f"{normal_profit_per_sqft:.2f} $",
            "Ajustement / PC": f"{sale_adjustment:.2f} $",
            "Prix vente final / PC": f"{final_sale_per_sqft:.2f} $",
            "Prix total projet": money(sale_total),
            "Profit final": money(profit),
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

    total_cost = (
        total_fabrication_cost
        + total_slab_cost
        + total_measurement_cost
        + total_sales_commission
        + total_designer_commission
    )
    final_profit = total_sales - total_cost
    final_profit_per_sqft = final_profit / total_project_sqft if total_project_sqft > 0 else 0

    requested_rows = create_requested_summary(all_pieces_df)
    placed_rows = create_placed_summary(slab_display_data)
    validation_rows = create_validation_summary(requested_rows, placed_rows)

    return {
        "pieces": pieces,
        "requested_rows": requested_rows,
        "placed_rows": placed_rows,
        "validation_rows": validation_rows,
        "split_piece_rows": split_piece_rows,
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
        "total_sales_before_discount": total_sales_before_discount,
        "client_discount_pct": client_discount_pct,
        "total_client_discount": total_client_discount,
        "total_slab_surface_sqft": total_slab_surface_sqft,
        "total_cost": total_cost,
        "final_profit": final_profit,
        "final_profit_per_sqft": final_profit_per_sqft,
        "total_measurement_cost": total_measurement_cost,
        "total_sales_commission": total_sales_commission,
        "designer_commission_pct": designer_commission_pct,
        "total_designer_commission": total_designer_commission,
        "total_client_discount": total_client_discount,
    }


def make_alternative_pieces_df(all_pieces_df, material_name):
    alt_df = all_pieces_df.copy()
    alt_df["Pierre / Couleur"] = material_name
    return alt_df


def build_comparison_pdf(project_name, project_date, comparison_rows, client_name="", client_address="", client_phone="", requested_by=""):
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
        ["Date prévue :", project_date.strftime("%Y-%m-%d")],
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
            Paragraph(clean_text(row["label"]), styles["BodyText"]),
            money(row["subtotal"]) if isinstance(row["subtotal"], (int, float)) else row["subtotal"],
            money(row["total_with_tax"]) if isinstance(row["total_with_tax"], (int, float)) else row["total_with_tax"],
            row["difference_display"],
            row["difference_percent_display"],
        ])

    comparison_table = Table(
        table_data,
        colWidths=[
            2.8 * inch,
            1.15 * inch,
            1.15 * inch,
            1.05 * inch,
            0.85 * inch,
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
            "Prise de mesure": money(values.get("Mesure", 0)),
            "Coût dalles attribué": money(values["Dalles"]),
            "Commission vendeur": money(values.get("Commission vendeur", 0)),
            "Commission designer": money(values.get("Commission designer", 0)),
            "Rabais client": money(values.get("Rabais client", 0)),
            "Coût total": money(values["Coût total"]),
            "Profit": money(values["Profit"]),
            "Profit / PC": f"{profit_pc:.2f} $",
        })

    return rows


def create_analysis_rows(data):
    total_project_sqft = data["total_project_sqft"]
    total_sales = data["total_sales"]
    gross_sales = data.get("total_sales_before_discount", total_sales)
    discount = data.get("total_client_discount", 0)
    total_fabrication_cost = data["total_fabrication_cost"]
    total_slab_cost = data["total_slab_cost"]
    total_measurement_cost = data["total_measurement_cost"]
    total_sales_commission = data["total_sales_commission"]
    total_designer_commission = data.get("total_designer_commission", 0)
    total_cost = data["total_cost"]
    final_profit = data["final_profit"]
    final_profit_per_sqft = data["final_profit_per_sqft"]



    return [
        {
            "Analyse": "Vente totale",
            "Valeur": money(gross_sales),
            "PC": f"{(gross_sales / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": f"Rabais client -{data.get('client_discount_pct', 0) * 100:.1f} %",
            "Valeur": f"-{money(discount)}",
            "PC": f"-{(discount / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Vente nette",
            "Valeur": money(total_sales),
            "PC": f"{(total_sales / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Coût dalles",
            "Valeur": money(total_slab_cost),
            "PC": f"{(total_slab_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Marge brute",
            "Valeur": money(total_sales - total_slab_cost),
            "PC": f"{((total_sales - total_slab_cost) / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Coût fabrication",
            "Valeur": money(total_fabrication_cost),
            "PC": f"{(total_fabrication_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Prise de mesure",
            "Valeur": money(total_measurement_cost),
            "PC": f"{(total_measurement_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Commission vendeur",
            "Valeur": money(total_sales_commission),
            "PC": f"{(total_sales_commission / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Commission designer",
            "Valeur": money(total_designer_commission),
            "PC": f"{(total_designer_commission / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
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
        topMargin=10,
        bottomMargin=10
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
        story.append(Paragraph(f"<b>Date prévue du projet :</b> {project_date.strftime('%Y-%m-%d')}", styles["Normal"]))
        story.append(Paragraph(f"<b>Date :</b> {date.today()}", styles["Normal"]))
        story.append(Spacer(1, 12))

        def add_table(title, rows):
            story.append(Paragraph(f"<b>{title}</b>", styles["Heading2"]))
            story.append(Spacer(1, 2))

            if not rows:
                story.append(Paragraph("Aucune donnée.", styles["Normal"]))
                story.append(Spacer(1, 10))
                return

            headers = list(rows[0].keys())
            table_data = [headers]

            for row in rows:
                table_data.append([str(row.get(h, "")) for h in headers])

            if title == "Analyse du prix":
                table = Table(
                    table_data,
                    colWidths=[1.45 * inch, 0.95 * inch, 0.75 * inch],
                    repeatRows=1
                )
            else:
                table = Table(table_data, repeatRows=1)

            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 5.5),
                ("PADDING", (0, 0), (-1, -1), 2),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))

            story.append(table)
            story.append(Spacer(1, 3))

        add_table("Matière", material_rows)
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
                project_date=project_date,
                project_note=item.get("project_note", ""),
                quote_profile_text=item.get("quote_profile_text", ""),
                quote_sink_cut_text=item.get("quote_sink_cut_text", ""),
                quote_measurement_install_text=item.get("quote_measurement_install_text", ""),
                quote_exclusions_text=item.get("quote_exclusions_text", ""),
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
                client_discount_pct=item.get("client_discount_pct", 0),
                client_discount_amount=item.get("total_client_discount", 0),
                laminage=item.get("laminage", False),
                laminage_pl=item.get("laminage_pl", 0),
                og=item.get("og", False),
                og_pl=item.get("og_pl", 0),
            )

            safe_project = safe_filename(project_name)
            safe_client = safe_filename(item["client_name"])
            safe_color = safe_filename(item["label"])

            filename = f"Soumission_{safe_project}_{safe_color}_{safe_client}.pdf"
            zip_file.writestr(filename, pdf_buffer.getvalue())
            production_pdf_buffer = build_production_pdf(
                project_name=project_name,
                project_date=project_date,
                slab_display_data=item["slab_display_data"],
                requested_rows=item["requested_rows"],
                placed_rows=item["placed_rows"],
                validation_rows=item["validation_rows"],
                split_piece_rows=item.get("split_piece_rows", [])
            )

            production_filename = f"Production_{safe_project}_{safe_color}_{safe_client}.pdf"
            zip_file.writestr(production_filename, production_pdf_buffer.getvalue())

        comparison_pdf = build_comparison_pdf(
            project_name=project_name,
            project_date=project_date,
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
    piece_dataframes = []

    for section_title, section_data in piece_sections:
        section_calc = section_data.copy()
        section_calc["Section"] = section_title
        piece_dataframes.append(section_calc)

    all_pieces_df = pd.concat(piece_dataframes, ignore_index=True)

    try:
        quote_data = calculate_quote_data(
            all_pieces_df,
            slab_options,
            production_cost_per_sqft,
            base_selling_price,
            minimum_profit_per_sqft,
            material_margin_pct,
            measurement_cost,
            sales_commission_pct,
            designer_commission_pct,
            client_discount_pct,
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
    requested_rows = quote_data["requested_rows"]
    placed_rows = quote_data["placed_rows"]
    validation_rows = quote_data["validation_rows"]

    total_project_sqft = quote_data["total_project_sqft"]
    total_slabs = quote_data["total_slabs"]
    total_slab_cost = quote_data["total_slab_cost"]
    total_fabrication_cost = quote_data["total_fabrication_cost"]
    total_sales = quote_data["total_sales"]
    total_slab_surface_sqft = quote_data["total_slab_surface_sqft"]
    total_cost = quote_data["total_cost"]
    total_measurement_cost = quote_data["total_measurement_cost"]
    total_sales_commission = quote_data["total_sales_commission"]
    final_profit = quote_data["final_profit"]
    final_profit_per_sqft = quote_data["final_profit_per_sqft"]

    all_remnants = []
    show_technical_tables = st.checkbox("Afficher les tableaux techniques", value=False)

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

    if show_technical_tables:
        st.header("Validation des quantités")
        st.subheader("Tableau demandé")
        st.dataframe(pd.DataFrame(requested_rows), use_container_width=True)
        st.subheader("Tableau regroupé / réparti")
        st.dataframe(pd.DataFrame(placed_rows), use_container_width=True)
        st.subheader("Validation des quantités")
        st.dataframe(pd.DataFrame(validation_rows), use_container_width=True)

    validation_ok = validation_is_successful(validation_rows)
    if validation_ok:
        if show_technical_tables:
            st.success("Validation réussie : toutes les quantités concordent.")
    else:
        st.error("La validation des quantités contient des écarts. La génération finale est arrêtée.")
        st.stop()

    
    st.header("Analyse de vente par section")

    section_rows = []

    for section_name, values in section_analysis.items():
        pc = values["PC"]
        profit_pc = values["Profit"] / pc if pc > 0 else 0
        vente_pc = values["Vente"] / pc if pc > 0 else 0

        section_rows.append({
            "Section": section_name,
            "PC": round(pc, 2),
            "Vente totale": money(values["Vente"]),
            "Vente / PC": f"{vente_pc:.2f} $",
            "Coût fabrication": money(values["Fabrication"]),
            "Prise de mesure": money(values.get("Mesure", 0)),
            "Coût dalles attribué": money(values["Dalles"]),
            "Commission vendeur": money(values["Commission vendeur"]),
            "Commission designer": money(values["Commission designer"]),
            "Rabais client": money(values.get("Rabais client", 0)),
            "Co\u00fbt total": money(values["Co\u00fbt total"]),
            "Profit": money(values["Profit"]),
            "Profit / PC": f"{profit_pc:.2f} $",
        })

    st.dataframe(pd.DataFrame(section_rows), use_container_width=True)

    st.header("Analyse du prix")

    analysis_df = pd.DataFrame(
    [
        {
            "Analyse": "Vente totale",
            "Valeur": money(quote_data.get("total_sales_before_discount", total_sales)),
            "PC": f"{(quote_data.get('total_sales_before_discount', total_sales) / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": f"Rabais client -{client_discount_pct * 100:.1f} %",
            "Valeur": f"-{money(quote_data.get("total_client_discount", 0))}",
            "PC": f"-{(quote_data.get('total_client_discount', 0) / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Vente nette",
            "Valeur": money(total_sales),
            "PC": f"{(total_sales / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Coût dalles",
            "Valeur": money(total_slab_cost),
            "PC": f"{(total_slab_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Marge brute",
            "Valeur": money(total_sales - total_slab_cost),
            "PC": f"{((total_sales - total_slab_cost) / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Coût fabrication",
            "Valeur": money(total_fabrication_cost),
            "PC": f"{(total_fabrication_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Prise de mesure",
            "Valeur": money(total_measurement_cost),
            "PC": f"{(total_measurement_cost / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Commission vendeur",
            "Valeur": money(total_sales_commission),
            "PC": f"{(total_sales_commission / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
        },
        {
            "Analyse": "Commission designer",
            "Valeur": money(quote_data.get("total_designer_commission", 0)),
            "PC": f"{(quote_data.get('total_designer_commission', 0) / total_project_sqft) if total_project_sqft > 0 else 0:.2f} $/pi²"
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
)

    st.table(analysis_df)

    if final_profit_per_sqft < minimum_profit_per_sqft:
        st.error("Le profit minimum n'est pas atteint.")
    else:
        st.success(f"Profit minimum atteint : {final_profit_per_sqft:.2f} $/pi²")

    gross_loss_total = total_slab_surface_sqft - total_project_sqft
    gross_loss_percent_total = (gross_loss_total / total_slab_surface_sqft) * 100 if total_slab_surface_sqft > 0 else 0

    loss_df = pd.DataFrame(
        [
            {"Analyse": "Surface totale des dalles achetées", "Valeur": f"{total_slab_surface_sqft:,.2f} pi²"},
            {"Analyse": "Surface utilisée projet", "Valeur": f"{total_project_sqft:,.2f} pi²"},
            {"Analyse": "Surface perdue brute", "Valeur": f"{gross_loss_total:,.2f} pi²"},
            {"Analyse": "% perte brute", "Valeur": f"{gross_loss_percent_total:.2f} %"},
        ]
    )

    if show_technical_tables:
        st.header("Analyse des pertes / retailles")
        st.table(loss_df)

    st.header("PDF")

    quote_items = []
    comparison_rows = []

    _, _, principal_total_with_tax = taxes_from_subtotal(total_sales)

    quote_items.append({
        "label": "soumission_principale",
        "project_note": project_note,
        "quote_profile_text": quote_profile_text,
        "quote_sink_cut_text": quote_sink_cut_text,
        "quote_measurement_install_text": quote_measurement_install_text,
        "quote_exclusions_text": quote_exclusions_text,
        "seller_name": seller_name,
        "seller_phone": seller_phone,
        "seller_email": seller_email,
        "client_name": client_name,
        "client_address": client_address,
        "client_phone": client_phone,
        "requested_by": requested_by,
        "laminage": laminage,
        "laminage_pl": laminage_pl,
        "og": og,
        "og_pl": og_pl,
        "section_analysis": section_analysis,
        "total_project_sqft": total_project_sqft,
        "total_sales": total_sales,
        "client_discount_pct": client_discount_pct,
        "total_client_discount": quote_data.get("total_client_discount", 0),
        "slab_display_data": slab_display_data,
        "material_rows": all_material_rows,
        "sales_rows": all_sales_rows,
        "section_rows": section_rows,
        "analysis_rows": analysis_df.to_dict("records"),
        "requested_rows": requested_rows,
        "placed_rows": placed_rows,
        "validation_rows": validation_rows,
        "split_piece_rows": quote_data.get("split_piece_rows", []),
    })

    comparison_rows.append({
        "label": ", ".join(materials),
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
                material_margin_pct,
                measurement_cost,
                sales_commission_pct,
                designer_commission_pct,
                client_discount_pct,
                edge_margin,
                saw_width
            )

            alt_label = f"alternative_{alt_index}_{safe_filename(material_name)}"
            _, _, alt_total_with_tax = taxes_from_subtotal(alt_data["total_sales"])
            difference = alt_total_with_tax - principal_total_with_tax
            difference_percent = (difference / principal_total_with_tax) * 100 if principal_total_with_tax > 0 else 0

            quote_items.append({
                "label": alt_label,
                "project_note": project_note,
                "quote_profile_text": quote_profile_text,
                "quote_sink_cut_text": quote_sink_cut_text,
                "quote_measurement_install_text": quote_measurement_install_text,
                "quote_exclusions_text": quote_exclusions_text,
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
                "client_discount_pct": client_discount_pct,
                "total_client_discount": alt_data.get("total_client_discount", 0),
                "slab_display_data": alt_data["slab_display_data"],
                "material_rows": alt_data["material_rows"],
                "sales_rows": alt_data["sales_rows"],
                "section_rows": create_section_rows(alt_data["section_analysis"]),
                "analysis_rows": create_analysis_rows(alt_data),
                "requested_rows": alt_data["requested_rows"],
                "placed_rows": alt_data["placed_rows"],
                "validation_rows": alt_data["validation_rows"],
                "split_piece_rows": alt_data.get("split_piece_rows", []),
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

    if show_technical_tables:
        st.header("Résumé des dalles par couleur")

    for item in slab_display_data:
        if show_technical_tables:
            st.success(
                f"Pierre / Couleur : {item['material']} | "
                f"Meilleure stratégie validée : {item['strategy']} "
                f"({item['slab_count']} dalles)"
            )

        # Calcul des retailles sans afficher les plans de coupe dans la page Streamlit.
        for idx, slab in enumerate(item["selected"], start=1):
            remnants = calculate_remnants(slab, min_remnant_width, min_remnant_height)

            for remnant in remnants:
                remnant["Pierre / Couleur"] = item["material"]
                remnant["Dalle"] = idx
                all_remnants.append(remnant)

    if show_technical_tables:
        st.header("Retailles restantes utiles")

    remnant_df = pd.DataFrame()
    useful_remnants_sqft = 0
    net_loss_sqft = gross_loss_total
    if all_remnants:
        remnant_df = pd.DataFrame(all_remnants)
        remnant_df = remnant_df[["Pierre / Couleur", "Dalle", "Type", "Largeur", "Hauteur", "Surface pi²"]]

        useful_remnants_sqft = remnant_df["Surface pi²"].sum()
        net_loss_sqft = gross_loss_total - useful_remnants_sqft

        if show_technical_tables:
            st.dataframe(remnant_df, use_container_width=True)
            st.info(f"Total des retailles utiles : {useful_remnants_sqft:.2f} pi²")
            st.info(f"Perte nette après retailles utiles : {net_loss_sqft:.2f} pi²")
    else:
        if show_technical_tables:
            st.warning("Aucune retaille utile selon les dimensions minimales indiquées.")
