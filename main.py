import asyncio
import aiohttp
import json
import sys
from rich.console import Console
from rich.prompt import Prompt
from rich import print as rprint
from pathlib import Path
import os
import csv
from datetime import datetime, timedelta
import shutil

console = Console()
SERVER_LIST_FILE = "srv_list.txt"
CACHE_DIR = Path("cache")
VALIDATION_CACHE_FILE = CACHE_DIR / "server_status.csv"
SERVER_METADATA_FILE = CACHE_DIR / "server_metadata.json"
CACHE_VALIDITY_MINUTES = 30

class ServerMetadata:
    def __init__(self):
        self.data = self._load_metadata()
    
    def _load_metadata(self) -> dict:
        if SERVER_METADATA_FILE.exists():
            return json.loads(SERVER_METADATA_FILE.read_text())
        return {}
    
    def save(self):
        SERVER_METADATA_FILE.write_text(json.dumps(self.data, indent=2))
    
    def get_note(self, server: str) -> str:
        return self.data.get(server, {}).get('note', '')
    
    def set_note(self, server: str, note: str):
        if server not in self.data:
            self.data[server] = {}
        self.data[server]['note'] = note
        self.save()
    
    def cache_models(self, server: str, models: list):
        if server not in self.data:
            self.data[server] = {}
        self.data[server]['models'] = models
        self.data[server]['models_cached_at'] = datetime.now().isoformat()
        self.save()
    
    def get_cached_models(self, server: str) -> list:
        return self.data.get(server, {}).get('models', [])

class ServerManager:
    def __init__(self):
        CACHE_DIR.mkdir(exist_ok=True)
        self.servers = self.load_servers()
        self.valid_servers = self.servers.copy()
        self.metadata = ServerMetadata()

    def load_servers(self) -> list:
        if not Path(SERVER_LIST_FILE).exists():
            Path(SERVER_LIST_FILE).write_text("")
        return [line.strip() for line in open(SERVER_LIST_FILE).readlines() if line.strip()]

    def save_servers(self):
        with open(SERVER_LIST_FILE, "w") as f:
            f.write("\n".join(self.servers))

    def _load_validation_cache(self) -> dict:
        if not VALIDATION_CACHE_FILE.exists():
            return {}
        
        cache = {}
        with open(VALIDATION_CACHE_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cache[row['server']] = {
                    'valid': row['valid'] == 'True',
                    'timestamp': datetime.fromisoformat(row['timestamp'])
                }
        return cache

    def _save_validation_cache(self, cache: dict):
        with open(VALIDATION_CACHE_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['server', 'valid', 'timestamp'])
            writer.writeheader()
            for server, data in cache.items():
                writer.writerow({
                    'server': server,
                    'valid': data['valid'],
                    'timestamp': data['timestamp'].isoformat()
                })

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
        cache = self._load_validation_cache()
        current_time = datetime.now()
        self.valid_servers = []
        invalid_servers = []
        
        for server in self.servers:
            cached = cache.get(server)
            if cached and (current_time - cached['timestamp']) < timedelta(minutes=CACHE_VALIDITY_MINUTES):
                if cached['valid']:
                    self.valid_servers.append(server)
                    note = self.metadata.get_note(server)
                    note_text = f" ({note})" if note else ""
                    rprint(f"[blue]✓ {server}{note_text} (cached)[/blue]")
                else:
                    invalid_servers.append(server)
                    rprint(f"[red]✗ {server} (cached)[/red]")
                continue

            rprint(f"[yellow]Validating {server}...[/yellow]")
            is_valid = await self.validate_server(server)
            cache[server] = {
                'valid': is_valid,
                'timestamp': current_time
            }
            
            if is_valid:
                self.valid_servers.append(server)
                note = self.metadata.get_note(server)
                note_text = f" ({note})" if note else ""
                rprint(f"[green]✓ {server}{note_text}[/green]")
            else:
                invalid_servers.append(server)
                rprint(f"[red]✗ {server}[/red]")

        self._save_validation_cache(cache)
        
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
                cache = self._load_validation_cache()
                current_time = datetime.now()
                self.valid_servers = [
                    server for server in self.servers
                    if cache.get(server, {}).get('valid', True) and
                    (current_time - cache.get(server, {}).get('timestamp', current_time)) < timedelta(minutes=CACHE_VALIDITY_MINUTES)
                ]
        return self.valid_servers

class LLMClient:
    def __init__(self, metadata: ServerMetadata):
        self.base_url = ""
        self.selected_model = None
        self.metadata = metadata

    async def select_server(self, servers: list) -> bool:
        if not servers:
            rprint("[red]No valid servers available[/red]")
            return False

        rprint("\n[cyan]Available servers:[/cyan]")
        for idx, server in enumerate(servers, 1):
            note = self.metadata.get_note(server)
            note_text = f" ({note})" if note else ""
            rprint(f"[blue]{idx}[/blue]. {server}{note_text}")
            
        rprint("[yellow]Enter 'n' followed by server number to add/edit note (e.g., 'n1')[/yellow]")
        
        while True:
            choice = Prompt.ask(
                "[cyan]Select server number or action[/cyan]",
                choices=[str(i) for i in range(1, len(servers) + 1)] + [f"n{i}" for i in range(1, len(servers) + 1)]
            )
            
            if choice.startswith('n'):
                server_idx = int(choice[1:]) - 1
                note = Prompt.ask(f"Enter note for {servers[server_idx]}")
                self.metadata.set_note(servers[server_idx], note)
                continue
                
            self.base_url = servers[int(choice)-1]
            if not self.base_url.startswith(("http://", "https://")):
                self.base_url = f"http://{self.base_url}"
            return True

    async def get_models(self) -> list:
        # Try to get cached models first
        cached_models = self.metadata.get_cached_models(self.base_url)
        if cached_models:
            return cached_models

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/v1/models") as response:
                if response.status == 200:
                    data = await response.json()
                    models = data.get("data", [])
                    # Cache the models
                    self.metadata.cache_models(self.base_url, models)
                    return models
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
    client = LLMClient(server_manager.metadata)
    
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
