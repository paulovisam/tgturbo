from InquirerPy import prompt, inquirer
from InquirerPy.exceptions import InvalidArgument
from InquirerPy.validator import PathValidator, EmptyInputValidator, NumberValidator
import os
from src.schemas import InputModel
from .banner import Banner


async def menu() -> InputModel:
    try:
        os.system("clear")
        Banner("TgTurbo").print_banner()
        input_model = InputModel()
        input_model.action = await inquirer.rawlist(
            message="O que deseja fazer hoje:",
            choices=["Clone", "Download Chat", "Download Media", "Upload", "Down_Up"],
        ).execute_async()
        input_model.action = input_model.action.lower() 

        if input_model.action == "clone":
            input_model.origin_id = await inquirer.text(
                message="Insira o ID do chat para copiar:",
            ).execute_async()
            input_model.dest_id = await inquirer.text(
                message="Insira o ID do chat de destino:",
                instruction="(Enter para criar)",
                default="",
            ).execute_async()

        elif input_model.action == "download chat":
            input_model.origin_id = await inquirer.text(
                message="Insira o ID do chat para download:",
            ).execute_async()

        elif input_model.action == "download media":
            input_model.origin_id = await inquirer.text(
                message="Insira o link da mídia para download:",
            ).execute_async()

        elif input_model.action == "upload":
            home_path = "~/" if os.name == "posix" else "C:\\"
            input_model.upload_path = await inquirer.filepath(
                message="Insira o caminho da pasta para upload:",
                validate=PathValidator(is_dir=True, message="Caminho inválido"),
                default=home_path,
                only_directories=True,
            ).execute_async()
            input_model.dest_id = await inquirer.text(
                message="Insira o ID do chat de destino:",
                instruction="(Enter para criar canal com nome da pasta)",
                default="",
            ).execute_async()
        elif input_model.action == "down_up":
            input_model.origin_id = await inquirer.text(
                message="Insira o ID do chat para baixar:",
            ).execute_async()
            input_model.dest_id = await inquirer.text(
                message="Insira o ID do chat para enviar:",
                instruction="(Enter para criar)",
                default="",
            ).execute_async()

        input_model.confirm = await inquirer.confirm(message="Confimar?", default=True).execute_async()
        return input_model
    
    except InvalidArgument:
        print("No available choices")
