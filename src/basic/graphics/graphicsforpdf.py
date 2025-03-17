from io import BytesIO
import matplotlib.pyplot as plt
import seaborn as sns
import json

def create_combined_graph(data):
    # Extract information from JSON
    labels = [store["label"] for store in data["data"]]
    revenue_week = [store["revenue_week"] for store in data["data"]]
    revenue_month = [store["revenue_month"] for store in data["data"]]
    revenue_year = [store["revenue_year"] for store in data["data"]]

    # Define custom colors
    week_color = (255 / 255, 226 / 255, 13 / 255)  # RGB (255,226,13) -> Yellow
    month_color = (214 / 255, 154 / 255, 129 / 255)  # RGB (214,154,129) -> Light Brown
    year_color = (197 / 255, 227 / 255, 132 / 255)  # RGB (197,227,132) -> Light Green

    # Create a combined figure with 3 rows
    fig = plt.figure(figsize=(16, 18))  # Общий размер фигуры
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 1])  # 3 строки, 2 столбца

    # Первый ряд: столбчатая диаграмма
    ax0 = fig.add_subplot(gs[0, :])  # Первая строка, весь столбец
    bar_width = 0.25  # Ширина столбцов
    index = range(len(labels))

    ax0.bar([i - bar_width for i in index], revenue_week, width=bar_width, label="Выручка за неделю",
            color=week_color)
    ax0.bar([i for i in index], revenue_month, width=bar_width, label="Выручка за месяц", color=month_color)
    ax0.bar([i + bar_width for i in index], revenue_year, width=bar_width, label="Выручка за год",
            color=year_color)
    ax0.set_xticks(index)
    ax0.set_xticklabels(labels, rotation=45, ha="right")
    ax0.set_xlabel("Магазины")
    ax0.set_ylabel("Выручка")
    ax0.set_title("Анализ выручки по периодам (Столбчатая диаграмма)")
    ax0.legend()
    ax0.grid(True, axis='y')

    # Второй и третий ряды: круговые диаграммы
    num_stores = len(data["data"])
    stores_per_row = 2  # 2 магазина в ряду, чтобы они не сливались

    for i, store in enumerate(data["data"]):
        sizes = [store["revenue_week"], store["revenue_month"], store["revenue_year"]]
        labels_pie = ["Выручка за неделю", "Выручка за месяц", "Выручка за год"]

        # Определяем, в каком ряду и столбце будет диаграмма
        row = (i // stores_per_row) + 1  # Второй или третий ряд
        col = i % stores_per_row  # Столбец в пределах ряда

        # Создаем подграфик для круговой диаграммы
        ax = fig.add_subplot(gs[row, col])  # Разделяем на два столбца
        ax.pie(sizes, labels=labels_pie, autopct='%1.1f%%', startangle=90,
               colors=[week_color, month_color, year_color])
        ax.set_title(f"{store['label']}")
        ax.axis('equal')  # Чтобы круговая диаграмма была круглой

    # Убираем пустые подграфики, если количество магазинов нечетное
    if num_stores % stores_per_row != 0:
        fig.delaxes(fig.add_subplot(gs[2, 1]))  # Удаляем пустой подграфик

    fig.suptitle("Анализ выручки по периодам", fontsize=16)
    plt.tight_layout(rect=[0, 0, 1, 0.96])  # Регулируем отступы

    # Сохраняем график в BytesIO
    img_bytes = BytesIO()
    plt.savefig(img_bytes, format='png')
    plt.close()

    img_bytes.seek(0)
    return img_bytes