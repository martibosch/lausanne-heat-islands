.PHONY: download_tree_canopy biophysical_table_shade station_measurements \
	landsat_features regression_df regressor swiss_dem tair_regr_maps \
	ref_et calibrate_ucm tair_ucm_maps


#################################################################################
# GLOBALS                                                                       #
#################################################################################

## variables
DATA_DIR = data
DATA_RAW_DIR := $(DATA_DIR)/raw
DATA_INTERIM_DIR := $(DATA_DIR)/interim
DATA_PROCESSED_DIR := $(DATA_DIR)/processed

MODELS_DIR = models

CODE_DIR = lausanne_heat_islands

NOTEBOOKS_DIR = notebooks

## rules
define MAKE_DATA_SUB_DIR
$(DATA_SUB_DIR): | $(DATA_DIR)
	mkdir $$@
endef
$(DATA_DIR):
	mkdir $@
$(foreach DATA_SUB_DIR, \
	$(DATA_RAW_DIR) $(DATA_INTERIM_DIR) $(DATA_PROCESSED_DIR), \
	$(eval $(MAKE_DATA_SUB_DIR)))
$(MODELS_DIR):
	mkdir $@


#################################################################################
# COMMANDS                                                                      #
#################################################################################

#################################################################################
# Utilities to be used in several tasks

## variables
CRS = EPSG:2056
### code
DOWNLOAD_S3_PY := $(CODE_DIR)/download_s3.py
UTILS_PY := $(CODE_DIR)/utils.py


#################################################################################
# LULC

## Download the agglom. extent, LULC, tree canopy and compute the shade column of
## the biophysical table
### variables
AGGLOM_EXTENT_DIR := $(DATA_RAW_DIR)/agglom-extent
AGGLOM_EXTENT_FILE_KEY = urban-footprinter/lausanne-agglom/agglom-extent.zip
AGGLOM_EXTENT_SHP := $(AGGLOM_EXTENT_DIR)/agglom-extent.shp
AGGLOM_LULC_FILE_KEY = urban-footprinter/lausanne-agglom/agglom-lulc.tif
AGGLOM_LULC_TIF := $(DATA_RAW_DIR)/agglom-lulc.tif
TREE_CANOPY_FILE_KEY = detectree/lausanne-agglom/tree-canopy.tif
TREE_CANOPY_TIF := $(DATA_RAW_DIR)/tree-canopy.tif
BIOPHYSICAL_TABLE_CSV := $(DATA_RAW_DIR)/biophysical-table.csv
BIOPHYSICAL_TABLE_SHADE_CSV := $(DATA_INTERIM_DIR)/biophysical-table-shade.csv
#### code
MAKE_BIOPHYSICAL_TABLE_SHADE_PY := $(CODE_DIR)/make_biophysical_table_shade.py

### rules
$(AGGLOM_EXTENT_DIR): | $(DATA_RAW_DIR)
	mkdir $@
$(AGGLOM_EXTENT_DIR)/%.zip: | $(AGGLOM_EXTENT_DIR)
	python $(DOWNLOAD_S3_PY) $(AGGLOM_EXTENT_FILE_KEY) $@
$(AGGLOM_EXTENT_DIR)/%.shp: $(AGGLOM_EXTENT_DIR)/%.zip
	unzip $< -d $(AGGLOM_EXTENT_DIR)
	touch $@
$(AGGLOM_LULC_TIF): | $(DATA_RAW_DIR)
	python $(DOWNLOAD_S3_PY) $(AGGLOM_LULC_FILE_KEY) $@
$(TREE_CANOPY_TIF): | $(DATA_RAW_DIR)
	python $(DOWNLOAD_S3_PY) $(TREE_CANOPY_FILE_KEY) $@
download_tree_canopy: $(TREE_CANOPY_TIF)
$(BIOPHYSICAL_TABLE_SHADE_CSV): $(AGGLOM_LULC_TIF) $(TREE_CANOPY_TIF) \
	$(BIOPHYSICAL_TABLE_CSV) $(MAKE_BIOPHYSICAL_TABLE_SHADE_PY)
	python $(MAKE_BIOPHYSICAL_TABLE_SHADE_PY) $(AGGLOM_LULC_TIF) \
		$(TREE_CANOPY_TIF) $(BIOPHYSICAL_TABLE_CSV) $@
biophysical_table_shade: $(BIOPHYSICAL_TABLE_SHADE_CSV)


#################################################################################
# STATIONS

### variables
STATION_RAW_DIR := $(DATA_RAW_DIR)/stations
LANDSAT_TILES_CSV := $(DATA_RAW_DIR)/landsat-tiles.csv
STATION_RAW_FILENAMES = station-locations.csv agrometeo-tre200s0.csv \
	meteoswiss-lausanne-tre000s0.zip meteoswiss-lausanne-tre200s0.zip \
	WSLLAF.txt VaudAir_EnvoiTemp20180101-20200128_EPFL_20200129.xlsx
STATION_RAW_FILEPATHS := $(addprefix $(STATION_RAW_DIR)/, \
	$(STATION_RAW_FILENAMES))
STATION_LOCATIONS_CSV := $(STATION_RAW_DIR)/station-locations.csv
STATION_TAIR_CSV := $(DATA_INTERIM_DIR)/station-tair.csv
#### code
MAKE_STATION_TAIR_DF_PY := $(CODE_DIR)/make_station_tair_df.py

### rules
$(STATION_RAW_DIR): | $(DATA_RAW_DIR)
	mkdir $@
define DOWNLOAD_STATION_DATA
$(STATION_RAW_DIR)/$(STATION_RAW_FILENAME): | $(STATION_RAW_DIR)
	python $(DOWNLOAD_S3_PY) \
		cantons/vaud/air-temperature/$(STATION_RAW_FILENAME) $$@
endef
$(foreach STATION_RAW_FILENAME, $(STATION_RAW_FILENAMES), \
	$(eval $(DOWNLOAD_STATION_DATA)))

$(STATION_TAIR_CSV): $(LANDSAT_TILES_CSV) $(STATION_RAW_FILEPATHS) \
	$(MAKE_STATION_TAIR_DF_PY) | $(DATA_INTERIM_DIR)
	python $(MAKE_STATION_TAIR_DF_PY) $(LANDSAT_TILES_CSV) \
		$(STATION_RAW_DIR) $@
station_measurements: $(STATION_TAIR_CSV)


#################################################################################
# REGRESSION

CODE_REGRESSION_DIR := $(CODE_DIR)/regression

## 1. Landsat features
### variables
REGRESSION_DIR := $(DATA_INTERIM_DIR)/regression
LANDSAT_FEATURES_NC := $(REGRESSION_DIR)/landsat-features.nc
# Notes:
# LC08_L1TP_195028_20190809_20190820_01_T1 has a "negligible" cloud stripe
# LC08_L1TP_195028_20180518_20180604_01_T1 excluded due to clouds affecting NDWI
#### code
MAKE_LANDSAT_FEATURES_PY := $(CODE_REGRESSION_DIR)/make_landsat_features.py

### rules
$(REGRESSION_DIR): | $(DATA_INTERIM_DIR)
	mkdir $@
$(LANDSAT_FEATURES_NC): $(LANDSAT_TILES_CSV) $(AGGLOM_EXTENT_SHP) \
	$(MAKE_LANDSAT_FEATURES_PY) | $(REGRESSION_DIR)
	python $(MAKE_LANDSAT_FEATURES_PY) $(LANDSAT_TILES_CSV) \
		$(AGGLOM_EXTENT_SHP) $@
landsat_features: $(LANDSAT_FEATURES_NC)

## 2. Download the data and assemble a data frame of the air temperature stations
### variables
REGRESSION_DF_CSV := $(REGRESSION_DIR)/regression-df.csv
#### code
MAKE_REGRESSION_DF_PY := $(CODE_REGRESSION_DIR)/make_regression_df.py

### rules
$(REGRESSION_DF_CSV): $(STATION_LOCATIONS_CSV) $(STATION_TAIR_CSV) \
	$(LANDSAT_FEATURES_NC) $(MAKE_REGRESSION_DF_PY)
	python $(MAKE_REGRESSION_DF_PY) $(STATION_LOCATIONS_CSV) \
		$(STATION_TAIR_CSV) $(LANDSAT_FEATURES_NC) $@
regression_df: $(REGRESSION_DF_CSV)

## 3. Train a regressor
### variables
REGRESSOR_JOBLIB := $(MODELS_DIR)/regressor.joblib
#### code
MAKE_REGRESSOR_PY := $(CODE_REGRESSION_DIR)/make_regressor.py

### rules
$(REGRESSOR_JOBLIB): $(REGRESSION_DF_CSV) $(MAKE_REGRESSOR_PY) | $(MODELS_DIR)
	python $(MAKE_REGRESSOR_PY) $< $@
regressor: $(REGRESSOR_JOBLIB)

## 4. Predict
### variables
#### first, download and reproject the dem
DHM200_DIR := $(DATA_RAW_DIR)/dhm200
DHM200_URI = \
	https://data.geo.admin.ch/ch.swisstopo.digitales-hoehenmodell_25/data.zip
DHM200_ASC := $(DHM200_DIR)/DHM200.asc
SWISS_DEM_TIF := $(DATA_INTERIM_DIR)/swiss-dem.tif
#### predicted air temperature data array
TAIR_REGR_MAPS_NC := $(DATA_PROCESSED_DIR)/tair-regr-maps.nc
#### code
MAKE_TAIR_REGR_MAPS_PY := $(CODE_REGRESSION_DIR)/make_tair_regr_maps.py

### rules
$(DHM200_DIR): | $(DATA_RAW_DIR)
	mkdir $@
$(DHM200_DIR)/%.zip: | $(DHM200_DIR)
	wget $(DHM200_URI) -O $@
$(DHM200_DIR)/%.asc: $(DHM200_DIR)/%.zip
	unzip -j $< 'data/DHM200*' -d $(DHM200_DIR)
	touch $@
#### reproject ASCII grid. See https://bit.ly/2WEBxoL
TEMP_VRT := $(DATA_INTERIM_DIR)/temp.vrt
$(SWISS_DEM_TIF): $(DHM200_ASC)
	gdalwarp -s_srs EPSG:21781 -t_srs $(CRS) -of vrt $< $(TEMP_VRT)
	gdal_translate -of GTiff $(TEMP_VRT) $@
	rm $(TEMP_VRT)
swiss_dem: $(SWISS_DEM_TIF)
$(TAIR_REGR_MAPS_NC): $(AGGLOM_EXTENT_SHP) $(STATION_TAIR_CSV) \
	$(LANDSAT_FEATURES_NC) $(SWISS_DEM_TIF) $(REGRESSOR_JOBLIB) \
	$(MAKE_TAIR_REGR_MAPS_PY) | $(DATA_PROCESSED_DIR)
	python $(MAKE_TAIR_REGR_MAPS_PY) $(AGGLOM_EXTENT_SHP) \
		$(STATION_TAIR_CSV) $(LANDSAT_FEATURES_NC) $(SWISS_DEM_TIF) \
		$(REGRESSOR_JOBLIB) $@
tair_regr_maps: $(TAIR_REGR_MAPS_NC)


#################################################################################
# InVEST urban cooling model

CODE_INVEST_DIR := $(CODE_DIR)/invest

## 0. Some code that we need for all the experiments
### variables
DATA_INVEST_DIR := $(DATA_INTERIM_DIR)/invest
REF_ET_NC := $(DATA_INVEST_DIR)/ref-et.nc
#### code
MAKE_REF_ET_PY := $(CODE_INVEST_DIR)/make_ref_et.py

### rules
$(DATA_INVEST_DIR): | $(DATA_INTERIM_DIR)
	mkdir $@
$(REF_ET_NC): $(AGGLOM_LULC_TIF) $(AGGLOM_EXTENT_SHP) $(STATION_TAIR_CSV) \
	$(MAKE_REF_ET_PY) | $(DATA_INVEST_DIR)
	python $(MAKE_REF_ET_PY) $(AGGLOM_LULC_TIF) $(AGGLOM_EXTENT_SHP) \
		$(STATION_TAIR_CSV) $@
ref_et: $(REF_ET_NC)

## 1. Calibrate the model
### variables
CALIBRATED_PARAMS_JSON := $(DATA_INVEST_DIR)/calibrated-params.json
#### code
MAKE_CALIBRATE_UCM_PY := $(CODE_INVEST_DIR)/make_calibrate_ucm.py

### rules
#### we do not list `$(AGGLOM_EXTENT_SHP)` as requirement because we are not
#### actually using it, just passing it because the InVEST urban cooling model
#### requires a shapefile for the area of interest
$(CALIBRATED_PARAMS_JSON): $(AGGLOM_LULC) $(BIOPHYSICAL_TABLE_SHADE_CSV) \
	$(REF_ET_NC) $(STATION_LOCATIONS_CSV) $(STATION_TAIR_CSV) \
	$(MAKE_CALIBRATE_UCM_PY)
	python $(MAKE_CALIBRATE_UCM_PY) $(AGGLOM_LULC_TIF) $(AGGLOM_EXTENT_SHP) \
		$(BIOPHYSICAL_TABLE_SHADE_CSV) $(REF_ET_NC) \
		$(STATION_LOCATIONS_CSV) $(STATION_TAIR_CSV) $@		
calibrate_ucm: $(CALIBRATED_PARAMS_JSON)

## 2. Simulate the air temperature maps
### variables
TAIR_UCM_MAPS_NC := $(DATA_PROCESSED_DIR)/tair-ucm-maps.nc
#### code
MAKE_TAIR_UCM_MAPS_PY := $(CODE_INVEST_DIR)/make_tair_ucm_maps.py

### rules
$(TAIR_UCM_MAPS_NC): $(CALIBRATED_PARAMS_JSON) $(AGGLOM_EXTENT_SHP) \
	$(AGGLOM_LULC_TIF) $(BIOPHYSICAL_TABLE_SHADE_CSV) $(REF_ET_NC) \
	$(STATION_TAIR_CSV) $(STATION_LOCATIONS_CSV) $(MAKE_TAIR_UCM_MAPS_PY) \
	| $(DATA_PROCESSED_DIR)
	python $(MAKE_TAIR_UCM_MAPS_PY) $(CALIBRATED_PARAMS_JSON) \
		$(AGGLOM_EXTENT_SHP) $(AGGLOM_LULC_TIF) \
		$(BIOPHYSICAL_TABLE_SHADE_CSV) $(REF_ET_NC) $(STATION_TAIR_CSV) \
		$(STATION_LOCATIONS_CSV) $@
tair_ucm_maps: $(TAIR_UCM_MAPS_NC)

#################################################################################
# Self Documenting Commands                                                     #
#################################################################################

.DEFAULT_GOAL := help

# Inspired by <http://marmelab.com/blog/2016/02/29/auto-documented-makefile.html>
# sed script explained:
# /^##/:
# 	* save line in hold space
# 	* purge line
# 	* Loop:
# 		* append newline + line to hold space
# 		* go to next line
# 		* if line starts with doc comment, strip comment character off and loop
# 	* remove target prerequisites
# 	* append hold space (+ newline) to line
# 	* replace newline plus comments by `---`
# 	* print line
# Separate expressions are necessary because labels cannot be delimited by
# semicolon; see <http://stackoverflow.com/a/11799865/1968>
.PHONY: help
help:
	@echo "$$(tput bold)Available rules:$$(tput sgr0)"
	@echo
	@sed -n -e "/^## / { \
		h; \
		s/.*//; \
		:doc" \
		-e "H; \
		n; \
		s/^## //; \
		t doc" \
		-e "s/:.*//; \
		G; \
		s/\\n## /---/; \
		s/\\n/ /g; \
		p; \
	}" ${MAKEFILE_LIST} \
	| LC_ALL='C' sort --ignore-case \
	| awk -F '---' \
		-v ncol=$$(tput cols) \
		-v indent=19 \
		-v col_on="$$(tput setaf 6)" \
		-v col_off="$$(tput sgr0)" \
	'{ \
		printf "%s%*s%s ", col_on, -indent, $$1, col_off; \
		n = split($$2, words, " "); \
		line_length = ncol - indent; \
		for (i = 1; i <= n; i++) { \
			line_length -= length(words[i]) + 1; \
			if (line_length <= 0) { \
				line_length = ncol - indent - length(words[i]) - 1; \
				printf "\n%*s ", -indent, " "; \
			} \
			printf "%s ", words[i]; \
		} \
		printf "\n"; \
	}' \
	| more $(shell test $(shell uname) = Darwin && echo '--no-init --raw-control-chars')
