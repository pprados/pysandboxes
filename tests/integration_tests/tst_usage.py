import asyncio
import sys

if __name__ == "__main__":
    from tests.integration_tests.sb_usage import main

    try:
        asyncio.run(main(sys.argv))
    except KeyboardInterrupt:
        pass
