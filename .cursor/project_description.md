# The repository midvatten is a QGIS Python plugin. 

* The main purpose is to store (mostly) hydrogeological measurements of various kind in a database and tools handling the data (import/export) and visualize the data in various forms for the users.
The plugin contains features to:
  * Import of data support various formats, from more general tables (read from csv-files or QGIS vector layers) to specific data formats from sensors like Van Essen Divers (exported from their software DiverOffice) and the water quality standard interlab4, and more.
  * Visualizing data is done as time series graphs (CustomPlot among others), stratigraphy plots (SectionPlot and StratigraphyPlot), and as tables with information of various kind collected from the database.
  * The plugin also contains tools for collecting data from the database and formatting it into tables used in reports, for example in Microsoft Word of Libre Office writer.
  * Finally the plugin also contains smaller convenience tools for the user, like "ValuesFromSelectedLayer"