# Optional data tables not fully integrated in the plugin

CREATE TABLE s_qual_lab /*Soil quality data*/(
obsid text not null
, depth double
, report text not null
, project text
, staff text
, date_time text
, anameth text
, parameter text not null
, reading_num double
, reading_txt text
, unit text
, comment text
, primary key(report, parameter)
, foreign key(obsid) references obs_points(obsid)
);

CREATE TABLE w_qual_logger /*Water quality from logger measurements*/(
 obsid text NOT NULL /*Obsid linked to obs_points.obsid*/
 , date_time text NOT NULL /*Date and Time for the observation*/
 , instrument text /*Instrument ID*/
 , parameter text NOT NULL /*Measured parameter*/
 , reading_num double /*Value as real number*/
 , unit text /*Unit*/
 , comment text /*Comment*/
 , PRIMARY KEY(obsid, date_time, instrument, parameter, unit)
 , FOREIGN KEY(obsid) REFERENCES obs_points(obsid)
 );

CREATE UNIQUE INDEX w_qual_logger_unit_unique_index_null ON w_qual_logger /* Index to stop duplicate values where unit is null */ (
obsid
, date_time
, instrument
, parameter
, COALESCE(unit, '<NULL>')
);

CREATE TABLE spatial_history /*Spatial history for obs_points*/ (
SPATIALITE id INTEGER PRIMARY KEY AUTOINCREMENT
POSTGIS id SERIAL PRIMARY KEY
, obsid TEXT NOT NULL
, valid_from_date TEXT NOT NULL /*date_time from when this spatial entry is valid (for example the well drill date).*/
, east double /*Eastern coordinate (in the corresponding CRS)*/
, north double /*Northern coordinate (in the corresponding CRS)*/
, ne_accur double /*Approximate inaccuracy for coordinates*/
, ne_source text /*Source for the given position*/
, h_toc double /*Elevation (masl) for the measuring point*/
, h_tocags double /*Distance from Measuring point to Ground Surface (m)*/
, h_gs double /*Ground Surface level (m).*/
, h_accur double /*Inaccuracy (m) for Measuring Point level*/
, h_syst text /*Reference system for elevation*/
, h_source text /*Source for the measuring point elevation (consultancy report or similar)*/
, valid BOOLEAN /*Specifies if this spatial entry is still valid. Set to False if a new measurement has made the entry not longer valid.*/
, FOREIGN KEY (obsid) REFERENCES obs_points (obsid) ON DELETE CASCADE
);

CREATE TABLE tem_data /*Raw data from TEM2Go Inversion Models*/(
SPATIALITE id INTEGER PRIMARY KEY AUTOINCREMENT
POSTGIS id SERIAL PRIMARY KEY
, obsid text NOT NULL --Obsid linked to obs_lines.obsid
, inversion_name TEXT NOT NULL -- Name of the model
, length double NOT NULL --Length along line
, elevation double --Elevation (masl) for top layer
, data_fit double -- Data fit
, doi double --Depth of investigation (data is unreliable below this depth)
, thickness TEXT -- String list with thickness of layers in meters, ex for inversion with 3 layers: [1.0, 4.0, 5.0]
, resistivity TEXT -- String list with resistivity of the layers, ex for inversion with 3 layers: [29.5, 150.4, 1001.6]
, comment text --Additional info
, UNIQUE (obsid, inversion_name, length)
, FOREIGN KEY (obsid) REFERENCES obs_lines(obsid)
);