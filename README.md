# Pi-Dar

A little radar for the Pimoroni Presto display that plugs into Pi-Sky.

Everything runs on the Presto. It draws the scope, serves the page, and reads [Pi-Sky](https://github.com/monkeymademe/pi-sky). Pi-Sky is only read, never modified. Until a receiver is available, the scope uses simulated traffic.

The top of the screen is north. An aircraft above the centre is north of the antenna, and one to the right is east.

## On the Presto

Copy `wifi_config.example.json` to `wifi_config.json` and fill in the network name and password. `wifi_config.json` is left out of the repository.

Copy this folder onto the Presto. The program, the page, the font, and `config.json` are already in the place the board reads.

The boot screen shows the Presto's address. Open the page at `http://` that address. The Presto has to be on the Wi-Fi for a browser to reach that page, and for the board to reach Pi-Sky.

Open Sans is licensed under the SIL Open Font License. The license is in `OFL.txt`.

## The page

Saving on the page changes the scope on the Presto.

- Simulated traffic, or a Pi-Sky receiver
- The Pi-Sky address
- Antenna latitude and longitude, used as the centre while simulating
- Range: 10, 25, 50, 100, 150, or 250 km
- How many simulated aircraft, and how many callsigns to draw
- Theme: Phosphor, Amber, Arctic, Night, or Day

Tap a blip on the Presto, or a row on the page, for the flight card. On the Presto, tap the card again to return to the scope. An empty tap on the scope does nothing.

## Pi-Sky

Set the source to Pi-Sky and enter its home address, for example `http://192.168.1.20:5050`.

The Presto then reads only:

- `GET /api/config` for `receiver_lat` and `receiver_lon`
- `GET /api/dump1090/aircraft.json` for the live contacts
- one snapshot of `GET /events` for the route, airline, type, and registration on a tapped flight

In Pi-Sky mode the centre of the scope comes from that machine when the link is up. Simulated flights are marked simulated.

## Tests

The checks run on a computer, not on the Presto:

```bash
python3 -m unittest tests.test_radar
```
