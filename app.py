import streamlit as st
import pandas as pd

from db import (
    get_clients,
    get_templates,
    create_campaign,
    create_campaign_clients,
    get_campaigns,
    get_campaign_clients_joined,
    get_reactivation_candidates,
)

st.set_page_config(page_title="Email-рассылки", layout="wide")

st.title("Система email-рассылок и аналитики")

page = st.sidebar.radio("Страница", ["Рассылка", "Аналитика"])

if page == "Рассылка":
    st.header("Создание кампании")
    st.caption("Выберите шаблон, целевую аудиторию и создайте рассылку.")

    # Загружаем данные из БД
    templates_df = get_templates()
    clients_df = get_clients()

    if templates_df.empty:
        st.error("В базе нет ни одного шаблона писем.")
        st.stop()

    if clients_df.empty:
        st.error("В базе нет ни одного клиента.")
        st.stop()

    left_col, right_col = st.columns([2, 1])

    # ЛЕВАЯ КОЛОНКА: ФОРМА
    with left_col:
        st.subheader("Настройки кампании")

        # выбор шаблона
        template_options = {
            f"{row['id']}: {row['name']} ({row['type']})": row["id"]
            for _, row in templates_df.iterrows()
        }

        selected_template_label = st.selectbox(
            "Шаблон письма",
            options=list(template_options.keys()),
        )
        selected_template_id = template_options[selected_template_label]

        selected_template_type = templates_df.loc[
            templates_df["id"] == selected_template_id, "type"
        ].iloc[0]

        # подготовка списка клиентов
        client_options = {
            f"{row['id']}: {row['full_name']} ({row['email']}) [{row['segment']}]": row["id"]
            for _, row in clients_df.iterrows()
        }

        # автоподбор уснувших для WINBACK
        reactive_default_labels = []
        reactive_info = ""

        if selected_template_type.upper() == "WINBACK":
            inactive_days = 30
            react_df = get_reactivation_candidates(inactive_days)

            if not react_df.empty:
                react_ids = set(react_df["id"].tolist())
                reactive_default_labels = [
                    label for label, cid in client_options.items() if cid in react_ids
                ]
                reactive_info = (
                    f"Найдено {len(react_ids)} клиентов для реактивации "
                    f"(нет активности {inactive_days}+ дней)."
                )
            else:
                reactive_info = (
                    "Клиентов для реактивации по текущим критериям не найдено. "
                    "Выберите получателей вручную."
                )

        if reactive_info:
            st.info(reactive_info)

        selected_client_labels = st.multiselect(
            "Кому отправляем",
            options=list(client_options.keys()),
            default=reactive_default_labels,
        )
        selected_client_ids = [client_options[label] for label in selected_client_labels]

        # имя кампании
        default_campaign_name = "Новая кампания"
        campaign_name = st.text_input("Название кампании", value=default_campaign_name)

        create_clicked = st.button("Создать кампанию и отправить", use_container_width=True)

    # ПРАВАЯ КОЛОНКА: СВОДКА
    with right_col:
        st.subheader("Сводка кампании")
        st.markdown(f"**Выбранный шаблон:**  \n{selected_template_label}")
        st.markdown(f"**Тип кампании:**  `{selected_template_type}`")
        st.markdown(f"**Выбрано клиентов:**  **{len(selected_client_ids)}**")

        # небольшой превью-шаблон
        template_row = templates_df[templates_df["id"] == selected_template_id].iloc[0]
        with st.expander("Посмотреть тему и текст письма (общий вид)"):
            st.markdown(f"**Тема:** {template_row['subject']}")
            st.markdown("**Тело письма:**")
            st.write(template_row["body_male"])

    # Обработка кнопки
    if create_clicked:
        if not campaign_name.strip():
            st.warning("Введите название кампании.")
        elif not selected_client_ids:
            st.warning("Выберите хотя бы одного клиента.")
        else:
            campaign_id = create_campaign(
                name=campaign_name.strip(),
                template_id=selected_template_id,
                description=f"Создано из интерфейса Streamlit, шаблон id={selected_template_id}",
            )

            sent_count = create_campaign_clients(campaign_id, selected_client_ids)

            st.success(
                f"Кампания успешно создана (id={campaign_id}). "
                f"Отправлено писем: {sent_count}."
            )

            result_clients = clients_df[clients_df["id"].isin(selected_client_ids)][
                ["id", "full_name", "email", "segment"]
            ].rename(
                columns={
                    "id": "client_id",
                    "full_name": "ФИО",
                    "email": "Email",
                    "segment": "Сегмент",
                }
            )

            st.subheader("Список получателей кампании")
            st.dataframe(result_clients, use_container_width=True)

# СТРАНИЦА «АНАЛИТИКА»
elif page == "Аналитика":
    st.header("Аналитика кампаний")

    df = get_campaign_clients_joined()

    if df.empty:
        st.info("Данных по отправкам пока нет.")
        st.stop()

    # Приводим к удобному виду
    df["sent_at"] = pd.to_datetime(df["sent_at"])
    df["sent_date"] = df["sent_at"].dt.date
    df["status_norm"] = df["send_status"].str.upper()

    # Фильтры (sidebar)
    # Выбор кампаний
    campaign_names = sorted(df["campaign_name"].unique())
    selected_campaigns = st.sidebar.multiselect(
        "Выбор кампании",
        options=campaign_names,
        default=campaign_names,  # по умолчанию все
    )

    if selected_campaigns:
        df = df[df["campaign_name"].isin(selected_campaigns)]

    # Фильтр по дате отправки
    min_date = df["sent_date"].min()
    max_date = df["sent_date"].max()

    date_range = st.sidebar.date_input(
        "Период отправки",
        value=(min_date, max_date),
    )

    if isinstance(date_range, tuple):
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range

    if start_date and end_date:
        df = df[(df["sent_date"] >= start_date) & (df["sent_date"] <= end_date)]

    if df.empty:
        st.warning("По выбранным фильтрам данных нет.")
        st.stop()

    # метрики
    sent_total = len(df)
    opened_total = df["status_norm"].isin(["OPENED", "CLICKED"]).sum()
    clicked_total = (df["status_norm"] == "CLICKED").sum()

    open_rate_total = opened_total / sent_total if sent_total > 0 else 0
    click_rate_total = clicked_total / sent_total if sent_total > 0 else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Отправлено писем", sent_total)
    col2.metric("Open rate", f"{open_rate_total:.1%}")
    col3.metric("Click rate", f"{click_rate_total:.1%}")

    st.markdown("---")

    # Таблица метрик по кампаниям
    agg_campaign = (
        df.groupby("campaign_name")
          .agg(
              sent=("cc_id", "size"),
              opened=("status_norm", lambda s: s.isin(["OPENED", "CLICKED"]).sum()),
              clicked=("status_norm", lambda s: (s == "CLICKED").sum()),
          )
    )

    agg_campaign["open_rate"] = agg_campaign["opened"] / agg_campaign["sent"]
    agg_campaign["click_rate"] = agg_campaign["clicked"] / agg_campaign["sent"]

    agg_campaign = agg_campaign.reset_index().sort_values("sent", ascending=False)

    st.subheader("Метрики по кампаниям")
    st.dataframe(agg_campaign, use_container_width=True)

    st.markdown("---")

    tab_overall, tab_gender, tab_segment = st.tabs(
        ["Общая статистика", "По полу", "По сегментам"]
    )

    #вкладка "Общая статистика"
    with tab_overall:
        st.subheader("Метрики по кампаниям")

        st.dataframe(agg_campaign, use_container_width=True)

        st.subheader("Динамика отправок по дням")
        daily_agg = (
            df.groupby("sent_date")
            .agg(
                sent=("cc_id", "size"),
                opened=("status_norm", lambda s: s.isin(["OPENED", "CLICKED"]).sum()),
                clicked=("status_norm", lambda s: (s == "CLICKED").sum()),
            )
            .sort_index()
        )
        st.line_chart(daily_agg[["sent", "opened", "clicked"]])

    #вкладка "По полу"
    with tab_gender:
        st.subheader("Разрез по полу (gender)")
        df_gender = df.dropna(subset=["gender"])

        if df_gender.empty:
            st.info("Нет данных о поле клиентов.")
        else:
            agg_gender = (
                df_gender.groupby("gender")
                .agg(
                    sent=("cc_id", "size"),
                    opened=("status_norm", lambda s: s.isin(["OPENED", "CLICKED"]).sum()),
                    clicked=("status_norm", lambda s: (s == "CLICKED").sum()),
                )
            )
            agg_gender["open_rate"] = agg_gender["opened"] / agg_gender["sent"]
            agg_gender["click_rate"] = agg_gender["clicked"] / agg_gender["sent"]

            st.write("Таблица по полу:")
            st.dataframe(agg_gender.reset_index(), use_container_width=True)

            st.write("График open_rate / click_rate по полу:")
            st.bar_chart(agg_gender[["open_rate", "click_rate"]])

    #вкладка "По сегментам"
    with tab_segment:
        st.subheader("Разрез по сегментам (segment)")
        df_segment = df.dropna(subset=["segment"])

        if df_segment.empty:
            st.info("Нет данных о сегментах клиентов.")
        else:
            agg_segment = (
                df_segment.groupby("segment")
                .agg(
                    sent=("cc_id", "size"),
                    opened=("status_norm", lambda s: s.isin(["OPENED", "CLICKED"]).sum()),
                    clicked=("status_norm", lambda s: (s == "CLICKED").sum()),
                )
            )
            agg_segment["open_rate"] = agg_segment["opened"] / agg_segment["sent"]
            agg_segment["click_rate"] = agg_segment["clicked"] / agg_segment["sent"]

            st.write("Таблица по сегментам:")
            st.dataframe(agg_segment.reset_index(), use_container_width=True)

            st.write("График open_rate / click_rate по сегментам:")
            st.bar_chart(agg_segment[["open_rate", "click_rate"]])

