from flask import Flask, render_template, request
import pandas_datareader.data as web
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import requests
import re
import time
from bokeh.plotting import figure, show, output_file
from bokeh.embed import components
from bokeh.resources import CDN
from bokeh.models.annotations import BoxAnnotation


app=Flask(__name__)

@app.route('/plot/')
def plot():

    return render_template("plot.html", text=str("Please key in inputs and click the 'Submit' button to generate chart!"))


@app.route('/success-table', methods=['POST'])
def success_table():
    if request.method=="POST":
         #Stock Ticker Input
         #returns lookback period (in days)
        #bottom [] percentile of returns
        #input for stock price period (in years)
        try:
            company_name = request.form['Company Name']
            Ticker = request.form['Ticker']
            ReturnsLBperiod = int(request.form['ReturnsLBperiod'])
            ReturnsQuantile = float(request.form['ReturnsQuantile'])
            StockPricePeriod = int(request.form['StockPricePeriod'])


            end = datetime.now()
            start = datetime(end.year-StockPricePeriod, end.month, end.day)

            df=web.DataReader(Ticker, 'yahoo', start=start, end=end)

            '''Scrape Reuters Search'''


            def get_headlines(links_site):
                '''scrape the html of the site'''
                resp = requests.get(links_site)

                if not resp.ok:
                    return None

                html = resp.content

                s = str(html)

                '''Extract raw data'''
                headlines = re.findall(r'headline: "(.*?)",', s)
                dates = re.findall(r'date: "(.*?)",', s)
                links = re.findall(r'href: "(.*?)",', s)

                '''FORMAT ALL RAW DATA - format headlines, links and time'''

                '''Eliminate HTML tags from headline'''
                headlines = [re.sub('<[^<]+?>', '', item) for item in headlines]

                '''Edit links'''
                prefix = 'https://www.reuters.com'
                links = [prefix + x for x in links]

                '''Reformat time'''
                dates_stripped = [date.split(" ") for date in dates]

                index1 = 0

                while (index1 < len(dates)):
                    ''' Extract raw time and convert'''
                    year = dates_stripped[index1][2]
                    rawmonth = dates_stripped[index1][0]
                    raw_day = dates_stripped[index1][1]
                    month = time.strptime(rawmonth, "%B").tm_mon
                    day = raw_day.split(",")[0]

                    dates[index1] = str(year) + "-" + str(month) + "-" + str(day) + " 00:00:00"

                    index1 = index1 + 1

                dataframe = pd.DataFrame({'dates': dates, 'headlines': headlines, 'links': links})

                return dataframe


            def scrape_reuters(query, upper_page_limit=500):
                index = 1

                all_news = pd.DataFrame({'dates': [], 'headlines': [], 'links': []})

                '''Loop through subsequent Reuters pages'''
                while (index <= upper_page_limit):
                    site = 'https://www.reuters.com/assets/searchArticleLoadMoreJson?blob=' + query + '&bigOrSmall=big&articleWithBlog=true&sortBy=relevance&dateRange=all&numResultsToShow=10&pn=' + str(
                        index) + '&callback=addMoreNewsResults'

                    current_site_news = get_headlines(site)

                    all_news = pd.concat([all_news, current_site_news])

                    index = index + 1

                grouped_headlines = all_news.groupby('dates')['headlines'].apply(list)
                grouped_links = all_news.groupby('dates')['links'].apply(list)

                grouped_news = pd.DataFrame({'headlines': grouped_headlines, 'links': grouped_links})

                return grouped_news

            market_name='nasdaq composite'
            pages_to_scrape = 25
            counter_headlines = scrape_reuters(company_name, pages_to_scrape)  # scrape company news
            counter_headlines.columns = ['Company headlines', 'Company links']
            market_headlines = scrape_reuters(market_name, pages_to_scrape*0.4)  # scrape market news
            market_headlines.columns = ['Market headlines', 'Market links']
            all_headlines = pd.concat([counter_headlines, market_headlines], axis=1, sort=False)

            df["% Change"] = df["Adj Close"].pct_change(periods=ReturnsLBperiod) * 100
            threshold = df['% Change'].quantile(ReturnsQuantile)
            criteria_1 = df["% Change"] >= -threshold
            criteria_2 = df["% Change"] <= threshold

            df_filtered = df[criteria_1 | criteria_2]

            df_news = df_filtered.join(all_headlines)

            # creating Drawdown dates table
            df_news.index = pd.to_datetime(df_news.index)
            DDEnd = pd.to_datetime(pd.Series(df_news.index), format='%Y-%m-%d')
            DDStart = DDEnd - pd.Timedelta(days=ReturnsLBperiod)

            df2 = pd.DataFrame({"Returns Date": DDEnd, "% Return": np.round(df_news['% Change'].values, 2), str(company_name)+"-related Headlines": df_news['Company headlines'].values, "Source: Reuter links":df_news['Company links'].values, "Market Headlines": df_news['Market headlines'].values})
            df2=df2.dropna(how='all')    #to drop if all values in the row are nan


            ##creating candlestick chart:
            def inc_dec(c, o):
                if c > o:
                    value="Increase"
                elif c < o:
                    value="Decrease"
                else:
                    value="Equal"
                return value

            df["Status"]=[inc_dec(c,o) for c, o in zip(df.Close,df.Open)]
            df["Middle"]=(df.Open+df.Close)/2
            df["Height"]=abs(df.Close-df.Open)

            p=figure(x_axis_type='datetime', width=1000, height=300)
            p.title.text="Stock Price Chart for  "+str(company_name)+" from "+str(start.strftime('%m/%d/%Y'))+" to "+str(end.strftime('%m/%d/%Y'))+", shaded areas represent bottom "+str(round(100*ReturnsQuantile,1))+"%/ top "+ str(round(100*(1-ReturnsQuantile),1))+"% percentile of "+str(ReturnsLBperiod) +"-day returns"
            p.grid.grid_line_alpha=0.3

            hours_12=12*60*60*1000

            p.segment(df.index, df.High, df.index, df.Low, color="Black")

            p.rect(df.index[df.Status=="Increase"],df.Middle[df.Status=="Increase"],
                   hours_12, df.Height[df.Status=="Increase"],fill_color="#CCFFFF",line_color="black")

            p.rect(df.index[df.Status=="Decrease"],df.Middle[df.Status=="Decrease"],
                   hours_12, df.Height[df.Status=="Decrease"],fill_color="#FF3333",line_color="black")

            ##shading returns period on candlestick chart
            for i, j, k in zip(DDStart, DDEnd, df_news['% Change'].values):
                if k < 0:
                    p.add_layout(BoxAnnotation(left=i, right=j, fill_alpha=0.4, fill_color='red'))
                else:
                    p.add_layout(BoxAnnotation(left=i, right=j, fill_alpha=0.4, fill_color='green'))

            script1, div1 = components(p)
            cdn_js=CDN.js_files[0]
            cdn_css=CDN.css_files[0]
            return render_template("plot.html", text=df2.to_html (),
            script1=script1,
            div1=div1,
            cdn_css=cdn_css,
            cdn_js=cdn_js )


        except Exception as e:
            return render_template("plot.html", text=str(e))

@app.route('/')
def home():
    return render_template("home.html")

if __name__=="__main__":
    app.run(debug=True)
