import asyncio
import aiohttp
import json
import sys
from rich.console import Console
from rich.prompt import Prompt
from rich import print as rprint
from pathlib import Path
import os

console = Console()
SERVER_LIST_FILE = "srv_list.txt"

class ServerManager:
    def __init__(self):
        self.servers = self.load_servers()
        self.valid_servers = self.servers.copy()  # Initially all servers are considered valid

    def load_servers(self) -> list:
        if not Path(SERVER_LIST_FILE).exists():
            Path(SERVER_LIST_FILE).write_text("")
        return [line.strip() for line in open(SERVER_LIST_FILE).readlines() if line.strip()]

    def save_servers(self):
        with open(SERVER_LIST_FILE, "w") as f:
            f.write("\n".join(self.servers))

    async def validate_server(self, server: str) -> bool:
        if not server.startswith(("http://", "https://")):
            server = f"http://{server}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{server}/v1/models", timeout=5) as response:
                    return response.status == 200
        except:
            return False

    async def validate_all_servers(self) -> list:
        self.valid_servers = []
        invalid_servers = []
        
        for server in self.servers:
            rprint(f"[yellow]Validating {server}...[/yellow]")
            if await self.validate_server(server):
                self.valid_servers.append(server)
                rprint(f"[green]✓ {server} is valid[/green]")
            else:
                invalid_servers.append(server)
                rprint(f"[red]✗ {server} is invalid[/red]")
        
        if invalid_servers:
            if Prompt.ask("[red]Remove invalid servers from file?[/red]", choices=["y", "n"]) == "y":
                self.servers = self.valid_servers
                self.save_servers()
                rprint("[green]Invalid servers removed from file[/green]")
        
        return self.valid_servers

    async def get_available_servers(self, validate_first: bool = False) -> list:
        if validate_first:
            if Prompt.ask(
                "\n[yellow]Would you like to validate servers?[/yellow]",
                choices=["y", "n"],
                default="n"
            ) == "y":
                await self.validate_all_servers()
            else:
                self.valid_servers = self.servers.copy()
        return self.valid_servers

class LLMClient:
    def __init__(self):
        self.base_url = ""
        self.selected_model = None
        
    async def select_server(self, servers: list) -> bool:
        if not servers:
            rprint("[red]No valid servers available[/red]")
            return False

        rprint("\n[cyan]Available servers:[/cyan]")
        for idx, server in enumerate(servers, 1):
            rprint(f"[blue]{idx}[/blue]. {server}")
            
        choice = Prompt.ask(
            "[cyan]Select server number[/cyan]",
            choices=[str(i) for i in range(1, len(servers) + 1)]
        )
        self.base_url = servers[int(choice)-1]
        if not self.base_url.startswith(("http://", "https://")):
            self.base_url = f"http://{self.base_url}"
        return True

    async def get_models(self) -> list:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/v1/models") as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", [])
                else:
                    console.print("[red]Failed to fetch models[/red]")
                    return []

    async def select_model(self, models: list) -> tuple[bool, str]:
        if not models:
            rprint("[red]No models available[/red]")
            return False, "retry"

        rprint("\n[cyan]Available models:[/cyan]")
        for idx, model in enumerate(models, 1):
            rprint(f"[blue]{idx}[/blue]. {model['id']}")
        rprint("[yellow]Enter 's' to change server[/yellow]")
            
        choice = Prompt.ask(
            "[cyan]Select model number or action[/cyan]",
            choices=[str(i) for i in range(1, len(models) + 1)] + ["s"]
        )
        
        if choice == "s":
            return False, "server"
            
        self.selected_model = models[int(choice)-1]['id']
        return True, ""

    async def generate(self, prompt: str) -> None:
        if not self.selected_model:
            console.print("[red]No model selected[/red]")
            return

        payload = {
            "model": self.selected_model,
            "prompt": prompt
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/generate",
                json=payload
            ) as response:
                async for line in response.content:
                    try:
                        data = json.loads(line)
                        if data.get("response"):
                            console.print(data["response"], end="")
                    except json.JSONDecodeError:
                        pass
                console.print()

async def main():
    server_manager = ServerManager()
    client = LLMClient()
    
    valid_servers = await server_manager.get_available_servers(validate_first=True)
    
    while True:
        if not await client.select_server(server_manager.valid_servers):
            return
            
        while True:
            models = await client.get_models()
            success, action = await client.select_model(models)
            
            if not success:
                if action == "server":
                    break  # Go back to server selection
                continue  # Retry model selection
            
            while True:
                try:
                    prompt = Prompt.ask("\n[cyan]Enter prompt[/cyan] ([yellow]'b'[/yellow] to change model, [yellow]'s'[/yellow] to change server)")
                    if prompt.lower() in ['b', 's']:
                        break
                    await client.generate(prompt)
                except KeyboardInterrupt:
                    rprint("\n[yellow]Exiting...[/yellow]")
                    return
            
            if prompt.lower() == 's':
                break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        rprint("\n[yellow]Goodbye![/yellow]")
