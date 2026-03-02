import asyncio
import base64
import logging
import os
import pathlib
import uuid
from typing import Any

from playwright.async_api import async_playwright
from playwright.async_api import Browser
from playwright.async_api import BrowserContext
from playwright.async_api import Page


DATA_FOLDER = pathlib.Path(__file__).parent.parent.parent / "data"
DEFAULT_CONFIG = {
    # Display options
    "cadWidth": 1200,
    "height": 1200,
    "treeWidth": 0,
    "theme": "light",
    "glass": True,
    "tools": False,
    # Render options
    "ambientIntensity": 1.0,
    "directIntensity": 1.1,
    "metalness": 0.3,
    "roughness": 0.65,
    "edgeColor": 0x707070,
    # Viewer options
    "ortho": True,
    "control": "trackball",
    "up": "Z",
}
DEFAULT_ARGS = (
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-webgl",
    "--ignore-gpu-blocklist",
    "--enable-unsafe-swiftshader",
)


class CADViewerService:
    """Service class for loading and interacting with CAD viewer HTML using Playwright."""

    def __init__(
        self,
        data_dir: pathlib.Path | None = None,
        chrome_executable_path: pathlib.Path | None = None,
        args: tuple[str, ...] | None = None,
        logger: logging.Logger | None = None,
    ):
        if data_dir is None:
            data_dir = DATA_FOLDER
        self.data_dir = pathlib.Path(data_dir)
        self.chrome_executable_path = chrome_executable_path
        if self.chrome_executable_path is None:
            self.chrome_executable_path = os.environ.get(
                "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
            )
        self.args = args
        if self.args is None:
            self.args = DEFAULT_ARGS
        self.html_file = self.data_dir / "cad_viewer.html"
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._playwright = None
        self.logger = logger or logging.getLogger(__name__)

    async def start(self):
        """Start the Playwright browser and load the HTML file."""
        self._playwright = await async_playwright().start()
        self.logger.info(
            "Starting CAD viewer service with executable_path=%s, args=%s",
            self.chrome_executable_path,
            self.args,
        )
        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=self.args,
            executable_path=self.chrome_executable_path,
        )
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

        # Set up message handler for postMessage from the page
        async def handle_console(msg):
            self.logger.debug("Console: %s", msg)

        self.page.on("console", handle_console)

        # Load the HTML file
        html_path = f"file://{self.html_file.absolute()}"
        await self.page.goto(html_path, wait_until="networkidle")

    async def load_cad_data(
        self, data: dict[str, Any], config: dict[str, Any] | None = None
    ):
        """
        Load CAD model data into the viewer.

        Args:
            data: CAD model data dictionary
            config: Optional configuration dictionary
        """
        if self.page is None:
            raise RuntimeError("Service not started. Call start() first.")

        if config is None:
            config = DEFAULT_CONFIG

        message = {
            "model": data["data"],
            "config": config,
        }

        await self.page.evaluate(
            """(data) => {
                if (window.viewer && window.viewer.clear) {
                    window.viewer.clear();
                }
                window.loadModel(data);
            }""",
            message,
        )

        # Wait for viewer to be ready and data to be processed
        await asyncio.sleep(1.0)
        await self.page.wait_for_function(
            "window.viewer !== null && window.viewer !== undefined",
            timeout=5 * 1_000,
        )

    async def take_screenshot(self) -> bytes:
        """
        Take a screenshot of the CAD viewer.

        """
        if self.page is None:
            raise RuntimeError("Service not started. Call start() first.")

        task_id = uuid.uuid4().hex
        # Call getImage directly and wait for the promise to resolve
        result = await self.page.evaluate(
            """
            async (filename) => {
                if (!window.getImage) {
                    throw new Error('getImage function not available');
                }
                return await window.getImage(filename);
            }
            """,
            task_id,
        )

        if not isinstance(result, dict):
            raise RuntimeError(f"Invalid screenshot response type: {type(result)}")

        if "dataUrl" not in result:
            raise RuntimeError(f"Unexpected screenshot response: {result}")

        data_url = result["dataUrl"]
        if not data_url.startswith("data:image"):
            raise RuntimeError(f"Invalid screenshot data format: {data_url[:50]}...")

        base64_data = data_url.split(",")[1]
        return base64.b64decode(base64_data)

    async def stop(self):
        """Stop the browser and clean up resources."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

        self.page = None
        self.context = None
        self.browser = None
        self._playwright = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
