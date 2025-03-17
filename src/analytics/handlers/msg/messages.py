import os
from io import BytesIO
import pandas as pd
from fpdf import FPDF
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB
from aiogram import Router
from aiogram.enums.parse_mode import ParseMode

from .msg_util import set_input_state, make_kb, make_kb_report_menu, back_current_step_btn, add_messages_to_delete
from ..types.msg_data import MsgData
from .headers import make_header
from ...api import get_reports  # Ensure this function exists in api.py
from ...constant.variants import all_departments, all_branches, all_types, all_periods, all_menu_buttons
from ...constant.text.recommendations import recommendations
from ..states import AnalyticReportStates
from ...constant.text.texts import text_functions, TextData
import config as cf

from aiogram import Bot

# Create bot and router instance (Dispatcher not used)
bot = Bot(token=cf.TOKEN)
router = Router()


# msg functions
async def department_msg(msg_data: MsgData) -> None:
    await set_input_state(msg_data.state, "report:department")

    assert msg_data.tgid is not None, "tgid not specified"
    departments = await all_departments(msg_data.tgid)

    print("Полученные подразделения:", departments)  # Отладочный вывод

    if not departments:
        await msg_data.msg.edit_text("Нет доступных подразделений.")
        return

    header = await make_header(msg_data) + "\n\n"
    text = header + "Выберите подразделение"
    kb = make_kb(departments)
    await msg_data.msg.edit_text(text=text, reply_markup=kb)


async def branch_msg(msg_data: MsgData) -> None:
    await set_input_state(msg_data.state, "report:branch")

    assert msg_data.tgid is not None, "tgid not specified"
    departments = await all_departments(msg_data.tgid)
    department_id = (await msg_data.state.get_data()).get("report:department")

    header = await make_header(msg_data) + "\n\n"
    text = header + "Укажите вид отчёта"
    kb = make_kb(all_branches)
    await msg_data.msg.edit_text(text=text, reply_markup=kb)


async def type_msg(msg_data: MsgData, type_indexes: list[int]) -> None:
    await set_input_state(msg_data.state, "report:type")

    header = await make_header(msg_data) + "\n\n"
    text = header + "Выберите"
    kb = make_kb(all_types, type_indexes)
    await msg_data.msg.edit_text(text=text, reply_markup=kb)


async def period_msg(msg_data: MsgData, period_indexes: list[int]) -> None:
    await set_input_state(msg_data.state, "report:period")

    header = await make_header(msg_data) + "\n\n"
    text = header + "Выберите"
    kb = make_kb(all_periods, period_indexes)
    await msg_data.msg.edit_text(text=text, reply_markup=kb)


async def menu_msg(msg_data: MsgData, buttons_indexes: list[int]) -> None:
    header = await make_header(msg_data) + "\n\n"
    text = header + "Выберите"
    kb = make_kb_report_menu(all_menu_buttons, buttons_indexes)
    await msg_data.msg.edit_text(text=text, reply_markup=kb)


async def test_msg(msg_data: MsgData) -> None:
    state_data = await msg_data.state.get_data()

    departments = await all_departments(msg_data.tgid)
    department_id = state_data.get("report:department")

    _department = departments.get(department_id)
    _type = state_data.get("report:type")
    _period = state_data.get("report:period")

    await msg_data.msg.edit_text(text=f"{_department=}\n\n{_type=}\n\n{_period=}")


# Menu messages
async def parameters_msg(msg_data: MsgData) -> None:
    state_data = await msg_data.state.get_data()

    report_type = state_data.get("report:type")
    period = state_data.get("report:period")

    loading_msg = await msg_data.msg.edit_text(text="Загрузка ⏳")

    try:
        reports = await get_reports(
            tgid=msg_data.tgid,
            state_data=state_data
        )

        back_kb = IKM(inline_keyboard=[[back_current_step_btn]])

        if None in reports:
            await loading_msg.edit_text(text="Не удалось загрузить отчёт", reply_markup=back_kb)
            return

        header = await make_header(msg_data)
        header_msg = await msg_data.msg.answer(text=header)

        text_func = text_functions[report_type]
        text_msg = await msg_data.msg.answer(text=text_func(TextData(reports=reports, period=period)))

        await add_messages_to_delete(msg_data=msg_data, messages=[header_msg, text_msg])

        await msg_data.msg.answer(text="Вернуться назад?", reply_markup=back_kb)

        await loading_msg.delete()

        # After loading the reports, ask the user to choose the format
        await report_type_selection(msg_data)

    except Exception as e:
        await loading_msg.edit_text(text=f"Ошибка: {str(e)}", reply_markup=back_kb)


async def recommendations_msg(msg_data: MsgData) -> None:
    state_data = await msg_data.state.get_data()

    report_type = state_data.get("report:type")

    back_kb = IKM(inline_keyboard=[[back_current_step_btn]])

    if report_type == "revenue":
        await msg_data.msg.edit_text(text="в разработке", reply_markup=back_kb)
        return

    text = "<b>Рекомендации 💡</b>\n" + recommendations.get(report_type)

    if text is None:
        await msg_data.msg.edit_text(text="Не удалось получить рекомендации", reply_markup=back_current_step_btn)
        return

    await msg_data.msg.edit_text(text=text, reply_markup=back_current_step_btn)


# Inline keyboard for report type selection (PDF/Excel)
# Inline keyboard for report type selection (PDF/Excel)
async def report_type_selection(msg_data: MsgData) -> None:
    header = await make_header(msg_data) + "\n\n"
    text = header + "Выберите формат отчёта: PDF или Excel"

    kb = IKM(inline_keyboard=[
        [IKB(text="PDF", callback_data="report:send_pdf")],
        [IKB(text="Excel", callback_data="report:send_excel")],
    ])

    await msg_data.msg.edit_text(text=text, reply_markup=kb)



# Handle the user's callback when they choose to send the report in PDF format
@router.callback_query(lambda query: query.data == "report:send_pdf")
async def handle_send_pdf(query: types.CallbackQuery, state: FSMContext):
    await send_report(query.message, "pdf")
    await query.answer("Отчёт в формате PDF отправлен.")


# Handle the user's callback when they choose to send the report in Excel format
@router.callback_query(lambda query: query.data == "report:send_excel")
async def handle_send_excel(query: types.CallbackQuery, state: FSMContext):
    await send_report(query.message, "excel")
    await query.answer("Отчёт в формате Excel отправлен.")


# Function to generate and send the report (PDF/Excel)
async def send_report(message: Message, report_type: str) -> None:
    state_data = await message.state.get_data()
    report_type = state_data.get("report:type")

    try:
        # Generate the report based on the selected type (Excel or PDF)
        file_path = await generate_report(
            tgid=message.from_user.id,
            state_data=state_data,
            report_type=report_type
        )

        if file_path:
            # Send the generated report file
            if report_type == "pdf":
                with open(file_path, 'rb') as file:
                    await message.answer_document(file, caption="Ваш отчёт в формате PDF")
            elif report_type == "excel":
                with open(file_path, 'rb') as file:
                    await message.answer_document(file, caption="Ваш отчёт в формате Excel")

            # Clean up the file after sending
            os.remove(file_path)
        else:
            await message.answer("Не удалось создать отчёт.")
    except Exception as e:
        await message.answer(f"Ошибка при создании отчёта: {str(e)}")


async def generate_report(tgid: int, state_data: dict, report_type: str) -> str:
    # Получаем данные для отчета
    report_data = await get_report_data(tgid, state_data)  # Получаем данные для отчета

    # Если данных нет, возвращаем None
    if report_data is None:
        return None

    # В зависимости от типа отчета генерируем файл
    if report_type == "pdf":
        return await generate_pdf_report(report_data)
    elif report_type == "excel":
        return await generate_excel_report(report_data)
    else:
        return None


# Функция для генерации отчета в формате PDF
async def generate_pdf_report(report_data: dict) -> str:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font('Arial', 'B', 16)
    pdf.cell(200, 10, txt="Отчет", ln=True, align='C')

    pdf.ln(10)  # Отступ
    pdf.set_font('Arial', '', 12)

    for entry in report_data['data']:
        line = ' | '.join(f"{key}: {value}" for key, value in entry.items())
        pdf.cell(200, 10, txt=line, ln=True, align='L')

    file_path = f"reports/report_{report_data['id']}.pdf"
    pdf.output(file_path)

    return file_path


# Функция для генерации отчета в формате Excel
async def generate_excel_report(report_data: dict) -> str:
    df = pd.DataFrame(report_data['data'])

    file_path = f"reports/report_{report_data['id']}.xlsx"
    df.to_excel(file_path, index=False)

    return file_path


# Функция для получения данных для отчета
async def get_report_data(tgid: int, state_data: dict) -> dict:
    # Пример получения данных для отчета
    # В данном случае возвращаем примерные данные
    return {
        "id": 1,
        "data": [
            {"Дата": "2025-02-27", "Сумма": 1000},
            {"Дата": "2025-02-26", "Сумма": 2000},
        ]
    }
