# Weather App for Maxwelton Farm

# import modules
import os
import dash
import numpy as np
from dash import dcc, html, dash_table
from flask import Flask
import dash_bootstrap_components as dbc
import requests
import configparser
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px


# initiate the app
server = Flask(__name__)
app = dash.Dash(__name__,
                server=server,
                external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP]
                )
server = app.server

# set debug flag
DEBUG = False

# pull in data
def get_config():
    # read location information
    config = configparser.ConfigParser()
    config.read('config.ini')
    # get API key environment variable
    # also needs to be stored on the server
    config['weather']['api'] = os.environ.get('OPENWEATHER_API')
    return config['weather']

def get_weather_current(lat, long, api_key):
    # gets current weather at lat, long
    # returns json weather data
    api_url = "http://api.openweathermap.org/data/2.5/weather?lat={}&lon={}&units=imperial&appid={}".format(lat, long, api_key)
    if DEBUG:
        print(api_url)

    r = requests.get(api_url)
    return r.json()

def get_weather_forecast(lat, long, api_key):
    # gets forecasted weather at lat, long
    # returns json weather data
    api_url = "https://api.openweathermap.org/data/2.5/forecast?lat={}&lon={}&units=imperial&appid={}".format(lat, long, api_key)
    if DEBUG:
        print(api_url)

    r = requests.get(api_url)
    return r.json()

def get_weather_forecast_df(config):
    # Get forecasted air pressure
    forecast = get_weather_forecast(config['lat'], config['long'], config['api'])
    # convert json to data frame
    df1 = pd.DataFrame(forecast['list'])
    df2 = pd.json_normalize(df1['main'])
    df3 = pd.json_normalize(df1['weather']) # returns list of dictionaries
    df3 = pd.json_normalize(df3[0])
    df4 = pd.json_normalize(df1['wind'])

    # localize time from UTC to US/Pacific by converting to date format and back to string
    df1['dt_txt'] = pd.to_datetime(df1['dt_txt'])
    df1['dt_txt'] = df1['dt_txt'].dt.tz_localize('UTC').dt.tz_convert('US/Pacific')
    df1['dt_txt'] = df1['dt_txt'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # build result dataframe
    result = pd.concat([
        df1["dt_txt"],
        df2['temp'],
        df2["pressure"],
        df3['description'],
        df3['icon'],
        df1['pop'],
        df4['speed'],
        df4['gust'],
        df4['deg']
    ], axis=1)
    result.rename(columns={
        'dt_txt': 't',
        'pressure': 'Forecasted Pressure'
    }, inplace=True)

    return result

def est_tide_rise(pressure):
    # takes a barometric pressure and returns an estimated increase in tide due to low pressure
    # returns tide rise in feet

    # slope of -0.3937 in/mPA calculated from:
    #  tide_rise = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] # inches rise
    #mbar = [1013.003, 1010.463, 1007.923, 1005.383, 1002.843, 1000.303, 997.7631,
    #        995.2233, 992.6832, 990.1431, 987.6033, 985.0631, 982.5233, 979.9832,
    #        977.443, 974.9032, 972.3631] # matching pressure levels
    ref_pressure = 1013.003 # mPA
    slope = -0.3937  # inches / mPA

    if pd.isna(pressure):
        rise = np.nan   # no pressure data
    elif pressure < ref_pressure:
        # air pressure could cause higher water level
        rise = (1/12) * slope * (pressure - ref_pressure) # rise in feet
    else:
        rise = np.nan   # pressure effect is 0, NaN to show predicted plot

    return rise

def deg_to_compass(deg):
    # converts compass degrees to cardinal direction
    val = int((deg/22.5)+0.5)
    arr = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    direction = arr[(val % 16)]
    return direction

def get_tide_data(beginDate, endDate, product, stationId = "9444900", datum = "MLLW"):
    # takes date range, data product (prediction, water_level, pressure), station ID, and datum
    # builds API call
    # returns json data
    # get tide data from NOAA station
    # https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?begin_date=20231201&end_date=20231202&station=9444900&product=predictions&datum=MLLW&time_zone=lst_ldt&units=english&format=json
    # https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?begin_date=20231129&end_date=20231201&station=9444900&product=water_level&datum=MLLW&time_zone=lst_ldt&units=english&format=json

    api_url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?begin_date={}&end_date={}&station={}&product={}&datum={}&time_zone=lst_ldt&units=english&format=json".format(
        beginDate.strftime('%Y%m%d'),
        endDate.strftime('%Y%m%d'),
        stationId,
        product,
        datum,
    )
    if DEBUG:
        print(api_url)
    r = requests.get(api_url)

    return r.json()

def get_tide_df(config):
    FUTURE_DAYS = 5
    PAST_DAYS = 1

    # Get predicted tides
    json_predicted = get_tide_data(
        beginDate=datetime.today() - timedelta(days=PAST_DAYS),
        endDate=datetime.today() + timedelta(days=FUTURE_DAYS),
        product='predictions',
        stationId=config['tide_station'],
        datum = config['datum'],
        )

    # Get measured tides
    json_measured = get_tide_data(
        beginDate=datetime.today() - timedelta(days=PAST_DAYS),
        endDate=datetime.today(),
        product='water_level',
        stationId=config['tide_station'],
        datum = config['datum'],
        )
    station_name = json_measured["metadata"]['name']

    # Get measured air pressure
    json_pressure = get_tide_data(
        beginDate=datetime.today() - timedelta(days=PAST_DAYS),
        endDate=datetime.today(),
        product='air_pressure',
        stationId=config['tide_station'],
        datum = config['datum'],
        )

    # get 2 day air pressure prediction from OpenWeather (3 hour intervals)
    # TODO: reuse dataframe from weather forecast
    fc_press_df = get_weather_forecast_df(config)
    fc_press_df['t'] = pd.to_datetime(fc_press_df['t'])

    # convert json to dataframes and clean up
    p_df = pd.DataFrame(json_predicted["predictions"])
    p_df['t'] = pd.to_datetime(p_df['t'])
    p_df.rename(columns={'v': 'Predicted Height'}, inplace=True)

    a_df = pd.DataFrame(json_measured["data"])
    a_df['t'] = pd.to_datetime(a_df['t'])
    a_df.rename(columns={'v': 'Measured Height'}, inplace=True)
    a_df.drop(["s", "f", "q"], axis=1, inplace=True)   # remove unused data

    m_press_df = pd.DataFrame(json_pressure["data"])
    m_press_df['t'] = pd.to_datetime((m_press_df['t']))
    m_press_df.rename(columns={'v': 'Measured Pressure'}, inplace=True)
    m_press_df.drop(['f'], axis=1, inplace=True)

    # merge data frames
    result_df = pd.merge(left=p_df, right=a_df, how='left', left_on='t', right_on='t')
    result_df = pd.merge(left=result_df, right=m_press_df, how='left', left_on='t', right_on='t')
    result_df = pd.merge_asof(left=result_df, right=fc_press_df,  left_on='t', right_on='t')

    # convert data fields to plottable data types
    result_df["t"] = pd.to_datetime(result_df["t"])
    result_df[['Predicted Height','Measured Height','Measured Pressure','Forecasted Pressure']] = (
        result_df[['Predicted Height','Measured Height','Measured Pressure','Forecasted Pressure']].apply(pd.to_numeric)
    )

    # calculate new tide levels from predicted barometric pressure
    result_df['Estimated Height'] = result_df['Predicted Height'] + result_df['Forecasted Pressure'].apply(est_tide_rise)

    return result_df, station_name

# build web page components
config = get_config()
header_component = html.H1(children="Maxwelton Weather Dashboard", style={})

def build_cell(df, ind):
    # builds html table cell contents
    cols = ["temp", "speed", "gust", "pop"]
    #TODO: move formatting to original dataframe
    # remove decimals, convert to strings
    df[cols] = df[cols].astype(int).astype(str)

    desc = html.Div(df['description'][ind])
    #icon = html.Div(df['icon'][ind])
    # build temperature text
    temp = html.Div("Temp " + df['temp'][ind] + " °F")
    # build wind text
    wind = html.Div("Wind " + df['speed'][ind] + "mph from " + deg_to_compass(df['deg'][ind]))
    if df['speed'][ind] != df['gust'][ind]:
        gust = html.Div("Gusting to " + df['gust'][ind])
        wind = html.Div([wind, gust])
    # build rain text
    if df['pop'][ind] != '0':
        rain = html.Div(df['pop'][ind] + "% chance precip")
    else:
        rain = html.Div([""])
    cell = html.Td([desc, temp, wind, rain])

    return cell

def build_forecast_table(df):
    # Forecast Table
    # Column for each 3-hour forecast
    # Row for each day
    # Each cell contains: Description, Temp, PoP, Wind Speed, Gusts, Direction

    #TODO: after converting from UTC time, logic no longer works (midnight is 8 am)

    table_header = [html.Thead([
        html.Td("Date"),
        html.Td("Midnight"),
        html.Td("6 AM"),
        html.Td("Noon"),
        html.Td("6 PM"),
    ])]

    df['t'] = pd.to_datetime(df['t'])  # convert from string to datetime object
    df['hour'] = df['t'].dt.hour
    df['day'] = df['t'].dt.day

    table = []
    day_index = 0
    first_row = True
    row = []

    for ind in df.index:
        # for new day start a new table row
        if day_index == 0:
            # first time through
            day_index = df['day'][ind]
            # new row with date
            row = [html.Td(df['day'][ind])]

        elif df['day'][ind] != day_index:
            # subsequent times through, new day, new row
            day_index = df['day'][ind]
            table.append(html.Tr(row))
            # new row with date
            row = [html.Td(df['day'][ind])]

        # for a new hour, place the data in a cell
        if df['hour'][ind] == 0:
            # midnight
            if first_row:
                first_row = False
            cell = build_cell(df, ind)
            row.append(cell)
        elif df['hour'][ind] == 6:
            # 6am
            if first_row:
                row.append([html.Td()]) # blank cell
                first_row = False

            cell = build_cell(df, ind)
            row.append(cell)
        elif df['hour'][ind] == 12:
            # noon
            if first_row:
                row.append([html.Td(),html.Td()]) # blank cell
                first_row = False

            cell = build_cell(df, ind)
            row.append(cell)
        elif df['hour'][ind] == 18:
            # 6pm
            if first_row:
                row.append([html.Td(),html.Td(),html.Td()]) # blank cell
                first_row = False

            cell = build_cell(df, ind)
            row.append(cell)

    table_body = [html.Tbody(table, style={'font-size': '80%'})]
    # TODO: style table here
    table = dbc.Table(table_header + table_body,
                      bordered=True,
                      style={'text-align': 'center',
                             'margin': '10'},
                      )

    return table
def build_weather_comp(config):

    #TODO: Update real time weather from Tempest?

    current_data = get_weather_current(config['lat'], config['long'], config['api'])

    temp = "{0:.1f}".format(current_data["main"]["temp"])
    weather = current_data["weather"][0]["main"]
    weather_location = current_data["name"]
    pressure = current_data["main"]["pressure"]
    wind_speed = current_data["wind"]["speed"]
    wind_dir = deg_to_compass(current_data["wind"]["deg"])

    #TODO: reuse weather forecast
    #forecast_data = get_weather_forecast_df(config)
    #fc_table = build_forecast_table(forecast_data)

    #        html.Br,
    #        dcc.Link("NOAA Point Forecast for Maxwelton Beach", href="https://forecast.weather.gov/MapClick.php?lon=-122.43913&lat=47.94203"),

    wc = html.Div(children=[
        html.H3(["Weather in ", weather_location, ": ", weather], className="text-center"),
        html.H2([temp,"°F"], className="text-center"),
        html.H3(["Wind ",wind_speed," mph from ", wind_dir], className="text-center"),
        html.H3([pressure, " mbar"], className="text-center"),
        dcc.Link("Tempest Weather Station at Maxwelton Beach",
                 href="https://tempestwx.com/station/65019/"),
    ], style={'background-color':'light-blue',
              'display':'inline-block',
              'padding':20,
              'margin':10,
              'border-radius':10})
    return wc

df, station_name = get_tide_df(config)
def build_tide_comp(df, station_name):

    title = "".join(map(str,["Tide at ", station_name]))
    tideFig = px.line(df, x="t", y=["Predicted Height", "Measured Height", "Estimated Height"])
    tideFig.add_vline(x=datetime.now())
    tideFig.update_layout(
        title_text = title,
        title_x = 0.5,
        xaxis_title = "",
        yaxis_title = "Height MLLW (ft)",
        legend={'title':None},
    )
    # Legend location top right
    tideFig.update_layout(legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1
    ))
    # annual max and min tide levels (MLLW: min -4.3',  max 12')
    TIDE_MIN = -4
    TIDE_MAX = 14
    tideFig.update_yaxes(range=[TIDE_MIN, TIDE_MAX])
    tideFig.update_yaxes(zeroline=True, zerolinewidth=2, zerolinecolor='gray')

    # add inundation levels
    TIDE_INN_MOD = 11.2   # Tide level for moderate inundation
    TIDE_INN_SEV = 12     # Tide level for severe inundation
    tideFig.add_hrect(y0=TIDE_INN_MOD, y1=TIDE_INN_SEV, line_width=0, fillcolor='yellow', opacity=0.2)
    tideFig.add_hrect(y0=TIDE_INN_SEV, y1=TIDE_MAX, line_width=0, fillcolor='red', opacity=0.2)
    return tideFig

def build_pressure_comp(df):
    pressFig = px.line(df, x="t", y=["Measured Pressure", "Forecasted Pressure"])
    pressFig.add_vline(x=datetime.now())
    pressFig.update_layout(
        title_text="Barometric Pressure",
        title_x=0.5,
        xaxis_title="",
        yaxis_title="mBar",
        legend={'title':None},
     )
    # Legend location top right
    pressFig.update_layout(legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1
    ))
    # barometric pressure extremes
    PRESS_MIN = 970
    PRESS_MAX = 1050
    pressFig.update_yaxes(range=[PRESS_MIN, PRESS_MAX])

    return pressFig


# design the app layout
app.layout = html.Div(
    (
        dbc.Row(header_component),
        dbc.Row(build_weather_comp(config)),
        dbc.Row([dcc.Graph(figure=build_tide_comp(df, station_name))]),
        dbc.Row([dcc.Graph(figure=build_pressure_comp(df))]),
    )
)

#        dbc.Row([dcc.Link("Port Townsend Inundation Dashboard", href="https://tidesandcurrents.noaa.gov/inundationdb/inundation.html?id=9444900"),]),
#        dbc.Row([dcc.Link("Barometric Pressure Point Forecast",href="https://barometricpressure.app/results?lat=47.94203lng--122.43913"),]),


if __name__ == "__main__":
    # run the app
    app.run_server(debug=True)
