import joblib
import logging
import requests
import warnings
import numpy as np
import pandas as pd

from django.db import transaction

from io import StringIO
from datetime import datetime, date, timedelta
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

from .models import PredictionData
from apps.dataEngine.models import HistoricalWeather, EmployeeMaster


logger = logging.getLogger('general')

# Suppress all warnings
warnings.filterwarnings("ignore")


def get_prediction_data():
    # Query all data from the PredictionData table
    queryset = PredictionData.objects.all()

    # Convert the queryset into a list of dictionaries
    data = list(queryset.values())

    # Create a Pandas DataFrame from the list of dictionaries
    df_Absentism = pd.DataFrame(data)
    df_Absentism.dropna(subset=['date','attendance'], inplace=True)
    df_Absentism.dropna(how = 'all')
    df_Absentism = df_Absentism.rename(columns={'date': 'Dates','department': 'Line', 'attendance' : 'Status', 'section' : 'Section', 'name' : 'Name', 'empcode' : 'Empcode'})
    df_Absentism['Dates'] = pd.to_datetime(df_Absentism['Dates'])
    df_Absentism['Empcode'] = pd.to_numeric(df_Absentism['Empcode'], errors='coerce')
    # Drop rows where 'Empcode' is NaN (optional)
    df_Absentism = df_Absentism.dropna(subset=['Empcode'])
    # Convert to integers
    df_Absentism['Empcode'] = df_Absentism['Empcode'].astype(int)
    df_Absentism = df_Absentism[df_Absentism['Status'].isin(['A'])]
    df_Absentism = df_Absentism.sort_values(by='Dates', ascending=True)
    duplicate_check = ['Dates', 'Empcode', 'Name', 'Line', 'Section', 'Status']
    df_Absentism = df_Absentism.drop_duplicates(subset=duplicate_check, keep='first')
    # df_Absentism['Absence'] = df_Absentism['Status'].apply(lambda x: 1 if x == 'A' else 0)
    # #print(df_Absentism.head())

    return df_Absentism


def get_emp_master_data():
    # Query all data from the PredictionData table
    queryset = EmployeeMaster.objects.all()

    # Convert the queryset into a list of dictionaries
    data = list(queryset.values())

    # Create a Pandas DataFrame from the list of dictionaries
    df_emp_master = pd.DataFrame(data)
    return df_emp_master



def get_historical_weather_data():

    today = date.today() # Today's date
    # Calculate cutoff date: exactly 3 years ago from today, plus 1 day (to exclude the same day 3 years ago)
    # cutoff_date = date.today().replace(year=date.today().year - 3) + timedelta(days=1)
    startDate = date(2022, 1, 1) # Hardcoded to 1 Jan 2022
    endDate = today - timedelta(days=1) # As we don't have attendance data for today so fetching last day
    historical_weather_filter = {'datetime__range': (startDate, endDate)}

    # Query all data from the PredictionData table
    queryset = HistoricalWeather.objects.filter(**historical_weather_filter)

    # Convert the queryset into a list of dictionaries
    data = list(queryset.values())

    # Create a Pandas DataFrame from the list of dictionaries
    df_past_wf = pd.DataFrame(data)
    df_past_wf.dropna(how='all')

    df_past_wf['datetime'] = pd.to_datetime(df_past_wf['datetime'])
    df_past_wf = df_past_wf.drop_duplicates(subset='datetime', keep='last') # add this line
    df_past_wf = df_past_wf.drop(columns=['stations'])

    return df_past_wf



def get_future_weather_data():
    try:
        api_url = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/bangalore/next60days?unitGroup=us&include=days&key=H2FT4UP7KXRYK9L5N3E36X3N6&contentType=csv"


        # Setup retries
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))

        response = session.get(api_url, timeout=30, verify=False)
        response.raise_for_status()

        # response = requests.get(api_url, timeout=10, verify=False)
        # response.raise_for_status()  # Raises an error for bad status

        df_next60_wf = pd.read_csv(StringIO(response.text))

        # Convert to plain list and delete records from the database if they exist
        dates_list = df_next60_wf['datetime'].dropna().unique().tolist()
        # Step 1: Delete existing records in DB for the same dates
        HistoricalWeather.objects.filter(datetime__in=dates_list).delete()

        # Step 2: Calculate cutoff date for deletion (4 years before the earliest date in list)
        # smallest_date_str = min(dates_list)
        # smallest_date = datetime.strptime(smallest_date_str, '%Y-%m-%d')
        # cutoff_date = smallest_date.replace(year=smallest_date.year - 4).strftime('%Y-%m-%d')

        # Delete records older than 4 years before earliest future date
        # HistoricalWeather.objects.filter(datetime__lt=cutoff_date).delete()

        # Replace NaN values with defaults for numeric fields
        df_next60_wf.fillna({
            'severerisk': 0,
            'precip': 0,
            'precipprob': 0,
            'precipcover': 0,
            'snow': 0,
            'snowdepth': 0,
            'windgust': 0,
            'windspeed': 0,
            'winddir': 0,
            'sealevelpressure': 0,
            'cloudcover': 0,
            'visibility': 0,
            'solarradiation': 0,
            'solarenergy': 0,
            'uvindex': 0,
            'moonphase': 0,
        }, inplace=True)

        # Prepare objects for bulk create
        def safe_strip(value):
            return value.strip() if isinstance(value, str) else value
        
        objects_to_create = [
            HistoricalWeather(
                name=safe_strip(row.get('name')),
                datetime=row.get('datetime'),
                tempmax=row.get('tempmax'),
                tempmin=row.get('tempmin'),
                temp=row.get('temp'),
                feelslikemax=row.get('feelslikemax'),
                feelslikemin=row.get('feelslikemin'),
                feelslike=row.get('feelslike'),
                dew=row.get('dew'),
                humidity=row.get('humidity'),
                precip=row.get('precip', 0),
                precipprob=row.get('precipprob', 0),
                precipcover=row.get('precipcover', 0),
                preciptype=safe_strip(row.get('preciptype')),
                snow=row.get('snow', 0),
                snowdepth=row.get('snowdepth', 0),
                windgust=row.get('windgust'),
                windspeed=row.get('windspeed'),
                winddir=row.get('winddir'),
                sealevelpressure=row.get('sealevelpressure'),
                cloudcover=row.get('cloudcover'),
                visibility=row.get('visibility'),
                solarradiation=row.get('solarradiation'),
                solarenergy=row.get('solarenergy'),
                uvindex=row.get('uvindex'),
                severerisk=int(row.get('severerisk')) if not pd.isna(row.get('severerisk')) else None,
                sunrise=row.get('sunrise'),
                sunset=row.get('sunset'),
                moonphase=row.get('moonphase'),
                conditions=safe_strip(row.get('conditions')),
                description=safe_strip(row.get('description')),
                icon=safe_strip(row.get('icon')),
                stations=safe_strip(row.get('stations'))
            )
            for _, row in df_next60_wf.iterrows()
        ]

        # Use atomic transaction to ensure DB integrity
        with transaction.atomic():
            HistoricalWeather.objects.bulk_create(objects_to_create, batch_size=1000)

        logger.info(f"Inserted {len(objects_to_create)} future weather records.")

        df_next60_wf = df_next60_wf.drop(columns=['stations'], errors='ignore')
        return df_next60_wf
    except Exception as e:
        logger.error(f"Running except get_future_weather_data: {e}")
        return None
        

def prepare_training_data():
    df_Absentism = get_prediction_data()
    df_emp_master = get_emp_master_data()   
    active_emp_df = df_Absentism[df_Absentism['Empcode'].isin(df_emp_master['emp_code'])]
    
    df_past_wf = get_historical_weather_data()  
    df_next15_wf = get_future_weather_data()
        
    # Filter relevant columns from weather data
    weather_columns = ['datetime', 'tempmax', 'tempmin', 'humidity', 'precip', 'conditions']
    df_past_wf = df_past_wf[weather_columns]

    
    # Group attendance dataset by ['Dates', 'Line', 'Section',...etc...] and calculate total absent count
    attendance_grouped = (
        df_Absentism[df_Absentism['Status'] == 'A']
        .groupby(['Dates','Line', 'Section']) #Add Operations and Machinist TYPE if required ()
        .agg({'Status': 'count'})
        .reset_index()
        .rename(columns={'Status': 'Absent_Count'})
    )

    # Merge grouped attendance data with weather+skills data
    merged_data = pd.merge(
        attendance_grouped.astype({'Dates': 'datetime64[ns]'}),
        df_past_wf,
        left_on='Dates',
        right_on='datetime',
        how='inner'
    )
    # Drop redundant datetime column after merge
    merged_data.drop(columns=['datetime'], inplace=True)

    merged_data.columns = [
    'Dates','Line', 'Section',
    'Absent_Count', 'tempmax', 'tempmin', 'humidity', 'precip', 'conditions'
    ]
    return merged_data, df_next15_wf
    
    
# train the model dynamically using the merged historical data
def train_dynamic_model(merged_data, feature_importance_threshold=0.01):
    """
    Train the absenteeism prediction model with improved feature engineering
    and better handling of variations in the data.
    """
    #print("\nStarting model training...")

    # Rename 'Dates' to 'datetime' if needed
    if 'Dates' in merged_data.columns:
        merged_data.rename(columns={'Dates': 'datetime'}, inplace=True)

    # Convert datetime and create base features
    merged_data['datetime'] = pd.to_datetime(merged_data['datetime'])

    # Add seasonality features
    #print("\nAdding time-based features...")
    merged_data['month'] = merged_data['datetime'].dt.month
    merged_data['day_of_week'] = merged_data['datetime'].dt.dayofweek
    merged_data['is_weekend'] = (merged_data['day_of_week'] >= 5).astype(int)
    merged_data['quarter'] = merged_data['datetime'].dt.quarter
    merged_data['year'] = merged_data['datetime'].dt.year

    # Add cyclic encoding for time features
    merged_data['month_sin'] = np.sin(2 * np.pi * merged_data['month'] / 12)
    merged_data['month_cos'] = np.cos(2 * np.pi * merged_data['month'] / 12)
    merged_data['day_of_week_sin'] = np.sin(2 * np.pi * merged_data['day_of_week'] / 7)
    merged_data['day_of_week_cos'] = np.cos(2 * np.pi * merged_data['day_of_week'] / 7)    

    # Add shorter rolling statistics with multiple windows
    #print("Adding rolling statistics...")
    for window in [3, 5, 7, 14, 30, 60]:
        merged_data[f'rolling_mean_{window}d'] = merged_data.groupby(['Line', 'Section'])['Absent_Count'].transform(
            lambda x: x.rolling(window=window, min_periods=1).mean())
        merged_data[f'rolling_std_{window}d'] = merged_data.groupby(['Line', 'Section'])['Absent_Count'].transform(
            lambda x: x.rolling(window=window, min_periods=1).std())
        merged_data[f'rolling_max_{window}d'] = merged_data.groupby(['Line', 'Section'])['Absent_Count'].transform(
            lambda x: x.rolling(window=window, min_periods=1).max())

    # Add trend features
    #print("Adding trend features...")
    merged_data['trend_3d'] = merged_data['rolling_mean_3d'] - merged_data['rolling_mean_7d']
    merged_data['trend_5d'] = merged_data['rolling_mean_5d'] - merged_data['rolling_mean_14d']
    merged_data['trend_30d'] = merged_data['rolling_mean_30d'] - merged_data['rolling_mean_60d']

    # Add day-of-week specific statistics
    #print("Adding day-of-week statistics...")
    merged_data['dow_mean'] = merged_data.groupby(['Line', 'Section', 'day_of_week'])['Absent_Count'].transform('mean')
    merged_data['dow_max'] = merged_data.groupby(['Line', 'Section', 'day_of_week'])['Absent_Count'].transform('max')

    # Add lag features by Line and Section
    #print("Adding lag features...")
    for lag in range(1, 8):
        merged_data[f'lag_{lag}d'] = merged_data.groupby(['Line', 'Section'])['Absent_Count'].shift(lag)

    # Add weather interactions
    #print("Adding weather interactions...")
    merged_data['temp_humidity'] = merged_data['tempmax'] * merged_data['humidity']
    merged_data['temp_precip'] = merged_data['tempmax'] * merged_data['precip']
    
    # Calculate historical statistics before one-hot encoding
    #print("Calculating historical statistics...")
    stats_df = merged_data.groupby(['Line', 'Section'])['Absent_Count'].agg([
        ('mean', 'mean'),
        ('std', 'std'),
        ('p25', lambda x: x.quantile(0.25)),
        ('p75', lambda x: x.quantile(0.75)),
        ('max', 'max'),
        ('min', 'min'),
        ('median', 'median'),
        ('skew', 'skew'),
        ('kurt', lambda x: x.kurtosis())
    ])

    # Convert the index to strings for proper dictionary lookup later
    stats_df.index = stats_df.index.map(lambda x: (str(x[0]), str(x[1])))

    # Convert to dictionary
    historical_stats = {col: stats_df[col].to_dict() for col in stats_df.columns}

    # One-hot encode categorical variables
    #print("Encoding categorical features...")
    merged_data = pd.get_dummies(merged_data, columns=['Line', 'Section', 'conditions'], drop_first=False)

    # Define feature groups
    weather_features = ['tempmax', 'tempmin', 'humidity', 'precip', 'temp_humidity', 'temp_precip'] + [col for col in merged_data.columns if col.startswith('conditions_')]
    time_features = ['month_sin', 'month_cos', 'day_of_week_sin', 'day_of_week_cos', 'is_weekend', 'quarter', 'year', 'dow_mean', 'dow_max']
    rolling_features = [col for col in merged_data.columns if 'rolling_' in col]
    trend_features = ['trend_3d', 'trend_5d','trend_30d']
    lag_features = [col for col in merged_data.columns if 'lag_' in col]
    line_section_features = [col for col in merged_data.columns if col.startswith(('Line_', 'Section_'))]

    # Combine all features
    combined_features = weather_features + time_features + rolling_features + trend_features + lag_features + line_section_features

    # Prepare training data
    merged_data.dropna(inplace=True)
    X = merged_data[combined_features]
    y = merged_data['Absent_Count']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Compute sample weights based on target variable distribution
    #print("\nComputing sample weights...")
    sample_weights = compute_sample_weight(
        class_weight='balanced',
        y=pd.qcut(y_train, q=5, labels=False, duplicates='drop')
    )

    # Function to evaluate model performance
    def evaluate_model_performance(y_true, y_pred):
        return {
            'MSE': mean_squared_error(y_true, y_pred),
            'RMSE': np.sqrt(mean_squared_error(y_true, y_pred)),
            'MAE': mean_absolute_error(y_true, y_pred),
            'R2': r2_score(y_true, y_pred),
            'Within_One_Person_%': np.mean(abs(y_true - y_pred) <= 1) * 100
        }
    
    # Train initial model with improved parameters
    #print("\nTraining initial model...")
    model = RandomForestRegressor(
        n_estimators=300, #200
        min_samples_leaf=2, #1
        max_depth=25, #20
        min_samples_split=3, #2,
        max_features='sqrt',
        bootstrap=True,
        random_state=42,
        n_jobs=-1,
        verbose=1
    )
    model.fit(X_train, y_train, sample_weight=sample_weights)

    # Evaluate initial model
    y_pred = model.predict(X_test)
    metrics_all = evaluate_model_performance(y_test, y_pred)

    # Feature importance analysis
    feature_importances = pd.DataFrame({
        'Feature': combined_features,
        'Importance': model.feature_importances_
    }).sort_values('Importance', ascending=False)


    important_features = feature_importances[
        feature_importances['Importance'] >= feature_importance_threshold
    ]['Feature'].tolist()
    
    # Train final model with important features
    X_important = merged_data[important_features]
    X_train_imp, X_test_imp, y_train_imp, y_test_imp = train_test_split(
        X_important, y, test_size=0.2, random_state=42
    )

    # Compute sample weights for final model
    final_sample_weights = compute_sample_weight(
        class_weight='balanced',
        y=pd.qcut(y_train_imp, q=5, labels=False, duplicates='drop')
    )

    final_model = RandomForestRegressor(
        n_estimators=300, #200,
        min_samples_leaf=2,#1,
        max_depth=25,#20,
        min_samples_split=3,#2,
        max_features='sqrt',
        bootstrap=True,
        random_state=42,
        n_jobs=-1,
        verbose=1
    )
    final_model.fit(X_train_imp, y_train_imp, sample_weight=final_sample_weights)

    # Evaluate final model
    y_pred_imp = final_model.predict(X_test_imp)
    metrics_final = evaluate_model_performance(y_test_imp, y_pred_imp)
        
    # Save model and all statistics
    model_path = "absenteeism/models/dynamic_absenteeism_model.pkl"
    joblib.dump({
        'model': final_model,
        'features': important_features,
        'metrics_all_features': metrics_all,
        'metrics_important_features': metrics_final,
        'feature_importances': feature_importances.to_dict(),
        'historical_stats': historical_stats
    }, model_path)

    return {
        'important_features': important_features,
        'metrics_all_features': metrics_all,
        'metrics_important_features': metrics_final,
        'feature_importances': feature_importances,
        'historical_stats': historical_stats
    }   
        
    
# Function to predict absenteeism using future weather forecast
def predict_with_dynamic_model(future_weather, forecast_days, lags, line, section):
    """
    Improved prediction function with better handling of variations.
    """
    # #print(f"\nStarting predictions for Line: {line}, Section: {section}")

    model_data = joblib.load("absenteeism/models/dynamic_absenteeism_model.pkl")
    final_model = model_data['model']
    important_features = model_data['features']
    historical_stats = model_data.get('historical_stats', {})

    # Get historical statistics using string keys for proper lookup
    line_section_key = (str(line), str(section))
    hist_mean = historical_stats['mean'].get(line_section_key, 1.5)
    hist_std = historical_stats['std'].get(line_section_key, 0.5)
    hist_p25 = historical_stats['p25'].get(line_section_key, 1.0)
    hist_p75 = historical_stats['p75'].get(line_section_key, 2.0)
    hist_max = historical_stats['max'].get(line_section_key, 3.0)

    # Load future weather data
    future_weather.rename(columns={'Dates': 'datetime'}, inplace=True)
    future_weather['datetime'] = pd.to_datetime(future_weather['datetime'])
    available_days = len(future_weather)

    # Add seasonality features
    future_weather['month'] = future_weather['datetime'].dt.month
    future_weather['day_of_week'] = future_weather['datetime'].dt.dayofweek
    future_weather['is_weekend'] = (future_weather['day_of_week'] >= 5).astype(int)
    future_weather['quarter'] = future_weather['datetime'].dt.quarter
    future_weather['year'] = future_weather['datetime'].dt.year
    
    # Add cyclic encoding
    future_weather['month_sin'] = np.sin(2 * np.pi * future_weather['month'] / 12)
    future_weather['month_cos'] = np.cos(2 * np.pi * future_weather['month'] / 12)
    future_weather['day_of_week_sin'] = np.sin(2 * np.pi * future_weather['day_of_week'] / 7)
    future_weather['day_of_week_cos'] = np.cos(2 * np.pi * future_weather['day_of_week'] / 7)

    # Add weather interactions
    future_weather['temp_humidity'] = future_weather['tempmax'] * future_weather['humidity']
    future_weather['temp_precip'] = future_weather['tempmax'] * future_weather['precip']

    # Add Line and Section one-hot encoded features
    for feature in important_features:
        if feature.startswith('Line_'):
            feature_line = feature.split('Line_')[1]
            if str(line) == str(feature_line):
                future_weather[feature] = 1
            else:
                future_weather[feature] = 0
        elif feature.startswith('Section_'):
            feature_section = feature.split('Section_')[1]
            if str(section) == str(feature_section):
                future_weather[feature] = 1
            else:
                future_weather[feature] = 0
                
    # Create predictions DataFrame
    dates = []
    current_date = future_weather['datetime'].iloc[0]
    while len(dates) < forecast_days:
        if current_date.dayofweek != 6:  # 6 represents Sunday
            dates.append(current_date)
        current_date += pd.Timedelta(days=1)
    predictions_df = pd.DataFrame({'datetime': dates})
    date_range = pd.date_range(start=future_weather['datetime'].iloc[0],
                              periods=len(dates) + len(dates)//6 + 1,  # Add extra days to account for skipped Sundays
                              freq='D')

    # Initialize predictions list and rolling values
    predictions = []
    rolling_values = lags.copy()  # Last 7 days of historical values

    for day in range(forecast_days):
        if day < available_days:
            weather_row = future_weather.iloc[day]
            input_features = {feature: 0 for feature in important_features}

            # Fill weather features and interactions
            for feature in important_features:
                if feature in weather_row:
                    input_features[feature] = weather_row[feature]
                elif feature.startswith('conditions_') and feature in weather_row:
                    input_features[feature] = weather_row[feature]
                elif feature == 'temp_humidity':
                    input_features[feature] = weather_row['tempmax'] * weather_row['humidity']
                elif feature == 'temp_precip':
                    input_features[feature] = weather_row['tempmax'] * weather_row['precip']

            # Fill seasonality features
            seasonality_features = ['month_sin', 'month_cos', 'day_of_week_sin', 'day_of_week_cos',
                                  'is_weekend', 'quarter', 'year']
            for feature in seasonality_features:
                if feature in important_features:
                    input_features[feature] = weather_row[feature]
                    
            # Calculate rolling statistics for different windows
            for window in [3, 5, 7, 14, 30, 60]:
                if f'rolling_mean_{window}d' in important_features:
                    values = rolling_values[-window:]
                    input_features[f'rolling_mean_{window}d'] = np.mean(values) if values else 0
                if f'rolling_std_{window}d' in important_features:
                    values = rolling_values[-window:]
                    input_features[f'rolling_std_{window}d'] = np.std(values) if len(values) > 1 else 0
                if f'rolling_max_{window}d' in important_features:
                    values = rolling_values[-window:]
                    input_features[f'rolling_max_{window}d'] = np.max(values) if values else 0

            # Add trend features
            if len(rolling_values) >= 14:
                if 'trend_3d' in important_features:
                    mean_3d = np.mean(rolling_values[-3:])
                    mean_7d = np.mean(rolling_values[-7:])
                    input_features['trend_3d'] = mean_3d - mean_7d
                if 'trend_5d' in important_features:
                    mean_5d = np.mean(rolling_values[-5:])
                    mean_14d = np.mean(rolling_values[-14:])
                    input_features['trend_5d'] = mean_5d - mean_14d
            else:
                if 'trend_3d' in important_features:
                    input_features['trend_3d'] = 0
                if 'trend_5d' in important_features:
                    input_features['trend_5d'] = 0
        
        
            # For days beyond weather forecast, use last known values and focus on patterns
            # input_features = {feature: 0 for feature in important_features}

            # Use cyclic encoding for extrapolated dates
            current_date = date_range[day]
            input_features['month_sin'] = np.sin(2 * np.pi * current_date.month / 12)
            input_features['month_cos'] = np.cos(2 * np.pi * current_date.month / 12)
            input_features['day_of_week_sin'] = np.sin(2 * np.pi * current_date.dayofweek / 7)
            input_features['day_of_week_cos'] = np.cos(2 * np.pi * current_date.dayofweek / 7)
            input_features['is_weekend'] = int(current_date.dayofweek >= 5)
            input_features['quarter'] = current_date.quarter
            input_features['year'] = current_date.year                
                                
        # Convert dictionary to list maintaining feature order
        input_features_list = [input_features[feature] for feature in important_features]

        # Make base prediction
        base_prediction = final_model.predict([input_features_list])[0]

        # Add trend-based adjustment
        if len(rolling_values) >= 3:
            recent_trend = np.mean(np.diff(rolling_values[-3:]))
            trend_adjustment = recent_trend * 0.1  # Small adjustment based on recent trend
        else:
            trend_adjustment = 0

        # Calculate adaptive standard deviation
        std_dev = min(hist_std, 0.15 * base_prediction)  # Reduced from 0.2 to 0.15 for more stability

        # Add controlled randomization with trend adjustment
        prediction = np.random.normal(base_prediction + trend_adjustment, std_dev)

        # Ensure prediction stays within historical bounds
        lower_bound = max(1, hist_p25 * 0.9)  # Don't go below 1 or too far below 25th percentile
        upper_bound = min(hist_max, hist_p75 * 1.1)  # Don't exceed historical max or too far above 75th percentile
        prediction = np.clip(prediction, lower_bound, upper_bound)
        prediction = np.round(prediction)
        predictions.append(prediction)
        rolling_values.append(prediction)  # Update rolling values for next prediction

    predictions_df['Predicted_Absent_Count'] = predictions
    return predictions_df        
    
def consolidated_predictions(future_weather, merged_data, output_path=None):
    """
    Generate predictions for all lines and sections with improved variation handling.
    """
    #print("\nStarting consolidated predictions...")

    # Get unique Line-Section combinations
    line_section_combos = merged_data[['Line', 'Section']].drop_duplicates()
    #print(f"Found {len(line_section_combos)} unique Line-Section combinations")

    # Initialize list to store predictions
    all_predictions = []
    # forecast_days_list = [7, 15, 30, 45, 60]
    forecast_days_list = [8, 17, 35, 52, 70]

    # Load model to get historical stats
    # #print("Loading model and historical statistics...")
    model_data = joblib.load("absenteeism/models/dynamic_absenteeism_model.pkl")
    historical_stats = model_data.get('historical_stats', {})

    for _, combo in line_section_combos.iterrows():
        line = str(combo['Line'])  # Convert to string to match historical stats keys
        section = str(combo['Section'])

        # Get historical statistics for this combination
        hist_mean = historical_stats['mean'].get((line, section))
        hist_std = historical_stats['std'].get((line, section))

        if hist_mean is None or hist_std is None:
            continue
        
        # Filter data for current line and section
        line_section_data = merged_data[
            (merged_data['Line'].astype(str) == line) &
            (merged_data['Section'].astype(str) == section)
        ]

        if len(line_section_data) == 0:
            continue

        # Get initial lags for this line/section
        initial_lags = line_section_data['Absent_Count'].tail(7).tolist()

        # Generate predictions for each forecast period
        for forecast_days in forecast_days_list:
            predictions = predict_with_dynamic_model(
                future_weather,
                forecast_days,
                initial_lags.copy(),
                line,
                section
            )

            predictions_df = predictions.copy()
            predictions_df['Line'] = line
            predictions_df['Section'] = section
            predictions_df['forecast_period'] = forecast_days

            # Add historical statistics for reference
            predictions_df['historical_mean'] = hist_mean
            predictions_df['historical_std'] = hist_std

            # Calculate deviation from historical mean
            predictions_df['deviation_from_mean'] = (
                predictions_df['Predicted_Absent_Count'] - hist_mean
            ) / hist_std

            all_predictions.append(predictions_df)
    
    # Combine all predictions
    consolidated_df = pd.concat(all_predictions, ignore_index=True)

    # Calculate summary statistics
    summary_stats = consolidated_df.groupby(['Line', 'Section']).agg({
        'Predicted_Absent_Count': ['mean', 'min', 'max'],
        'deviation_from_mean': ['mean', 'min', 'max']
    }).round(2)

    # Fix multi-level column names
    summary_stats.columns = [f"{col[0]}_{col[1]}" for col in summary_stats.columns]
             
    if consolidated_df is not None:
        # original_days = [7, 15, 30, 45, 60]
        # extended_days = [8, 17, 35, 52, 70]  # Days including skipped Sundays
        # days_map = dict(zip(extended_days, original_days))

        all_dataframes = []
        for days in forecast_days_list:
            print(f"\nSaving {days}-day predictions...")
            period_df = consolidated_df[consolidated_df['forecast_period'] == days].copy()
 
            
            period_df['date'] = pd.to_datetime(period_df['datetime']).dt.date
            period_df['day_of_week'] = pd.to_datetime(period_df['datetime']).dt.day_name()

            columns_order = [
                'date', 'day_of_week', 'line', 'section',
                'predicted_absent_count', 'historical_mean', 'historical_std',
                'deviation_from_mean'
            ]
  
            remaining_cols = [col for col in period_df.columns if col not in columns_order]

            # Append to the list
            all_dataframes.append(period_df)   
        final_dataframe = pd.concat(all_dataframes, ignore_index=True)
        
    # period_df['date'] = pd.to_datetime(period_df['datetime'])
    # Commenting below 2 lines as we're including today's data also
    # today = pd.Timestamp.now().date()
    # final_dataframe = final_dataframe[final_dataframe['date'] != today]

    replacement_map = {8: 7, 17: 15, 35: 30, 52: 45, 70: 60}
    final_dataframe['forecast_period'] = final_dataframe['forecast_period'].replace(replacement_map)

    # Calculate Saturday of month (returns 0 for non-Saturdays)
    final_dataframe['saturday_of_month'] = final_dataframe.apply(
        lambda x: (x['date'].day - 1) // 7 + 1 if x['day_of_week'].strip() == 'Saturday' else 0,
        axis=1
    )

    # Filter out rows where day_of_week is 'Sunday' or 'sunday'
    final_dataframe = final_dataframe[~final_dataframe['day_of_week'].str.lower().eq('sunday')]

    final_dataframe = final_dataframe[
        ~((final_dataframe['day_of_week'] == 'Saturday') & (~final_dataframe['saturday_of_month'].isin([1, 5])))
    ]

    final_dataframe = final_dataframe.drop('saturday_of_month', axis=1)        

    return final_dataframe    
    
def model_prediction():
    try:
        logger.info(f"Running try get_prediction_data\n")
        merged_data, df_next15_wf = prepare_training_data()        
        train_dynamic_model(merged_data)
        consolidated_df = consolidated_predictions(df_next15_wf, merged_data)
        print("Completed Consolidated Predictions")
        logger.info(f"Completed get_prediction_data\n")
        return consolidated_df
    except Exception as e:
        logger.info(f"Running except get_prediction_data {e} \n")
