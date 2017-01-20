/* globals analytics */
/**
 * @file Defines all models for the export page. Models map to python models in
 * corehq/apps/export/models/new.py
 *
 */

hqDefine('export/js/models.js', function () {
    var constants = hqImport('export/js/const.js');
    var utils = hqImport('export/js/utils.js');
    var urls = hqImport('hqwebapp/js/urllib.js');

    /**
     * ExportInstance
     * @class
     *
     * This is an instance of an export. It contains the tables to export
     * and other presentation properties.
     */
    var ExportInstance = function(instanceJSON, options) {
        options = options || {};
        var self = this;
        ko.mapping.fromJS(instanceJSON, ExportInstance.mapping, self);

        self.buildSchemaProgress = ko.observable(0);
        self.showBuildSchemaProgressBar = ko.observable(false);
        self.errorOnBuildSchema = ko.observable(false);
        self.schemaProgressText = ko.observable(gettext('Process'));

        // Detetrmines the state of the save. Used for controlling the presentaiton
        // of the Save button.
        self.saveState = ko.observable(constants.SAVE_STATES.READY);

        // True if the form has no errors
        self.isValid = ko.pureComputed(function() {
            if (!self.hasDailySavedAccess && self.is_daily_saved_export()) {
                return false;
            }
            return true;
        });

        // The url to save the export to.
        self.saveUrl = options.saveUrl;
        self.hasExcelDashboardAccess = Boolean(options.hasExcelDashboardAccess);
        self.hasDailySavedAccess = Boolean(options.hasDailySavedAccess);

        // If any column has a deid transform, show deid column
        self.isDeidColumnVisible = ko.observable(self.is_deidentified() || _.any(self.tables(), function(table) {
            return table.selected() && _.any(table.columns(), function(column) {
                return column.selected() && column.deid_transform();
            });
        }));

        self.hasHtmlFormat = ko.pureComputed(function() {
            return this.export_format() === constants.EXPORT_FORMATS.HTML;
        }, self);
        self.hasDisallowedHtmlFormat = ko.pureComputed(function() {
            return this.hasHtmlFormat() && !this.hasExcelDashboardAccess;
        }, self);

        self.export_format.subscribe(function (newFormat){
            // Selecting Excel Dashboard format automatically checks the daily saved export box
            if (newFormat === constants.EXPORT_FORMATS.HTML) {
                self.is_daily_saved_export(true);
            } else {
                if (!self.hasExcelDashboardAccess){
                    self.is_daily_saved_export(false);
                }
            }
        });
    };

    ExportInstance.prototype.onBeginSchemaBuild = function(exportInstance, e) {
        var self = this,
            $btn = $(e.currentTarget),
            errorHandler,
            successHandler,
            buildSchemaUrl = urls.reverse('build_schema', this.domain()),
            identifier = ko.utils.unwrapObservable(this.case_type) || ko.utils.unwrapObservable(this.xmlns);

        this.showBuildSchemaProgressBar(true);
        this.buildSchemaProgress(0);

        self.schemaProgressText(gettext('Processing...'));
        $btn.attr('disabled', true);
        $btn.addClass('disabled');
        $btn.addSpinnerToButton();

        errorHandler = function() {
            $btn.attr('disabled', false);
            $btn.removeSpinnerFromButton();
            $btn.removeClass('disabled');
            self.errorOnBuildSchema(true);
            self.schemaProgressText(gettext('Process'));
        };

        successHandler = function() {
            $btn.removeSpinnerFromButton();
            self.schemaProgressText(gettext('Processing Complete. Refresh page.'));
        };

        $.ajax({
            url: buildSchemaUrl,
            type: 'POST',
            data: {
                type: this.type(),
                app_id: this.app_id(),
                identifier: identifier,
            },
            dataType: 'json',
            success: function(response) {
                self.checkBuildSchemaProgress(response.download_id, successHandler, errorHandler);
            },
            error: errorHandler,
        });
    };

    ExportInstance.prototype.checkBuildSchemaProgress = function(downloadId, successHandler, errorHandler) {
        var self = this,
            buildSchemaUrl = urls.reverse('build_schema', this.domain());

        $.ajax({
            url: buildSchemaUrl,
            type: 'GET',
            data: {
                download_id: downloadId,
            },
            dataType: 'json',
            success: function(response) {
                if (response.success) {
                    self.buildSchemaProgress(100);
                    self.showBuildSchemaProgressBar(false);
                    successHandler();
                    return;
                }

                if (response.failed) {
                    self.errorOnBuildSchema(true);
                    return;
                }

                self.buildSchemaProgress(response.progress.percent || 0);
                if (response.not_started || response.progress.current !== response.progress.total) {
                    window.setTimeout(
                        self.checkBuildSchemaProgress.bind(self, response.download_id, successHandler, errorHandler),
                        2000
                    );
                }
            },
            error: errorHandler,
        });
    };

    ExportInstance.prototype.getFormatOptionValues = function() {
        return _.map(constants.EXPORT_FORMATS, function(value) { return value; });
    };

    ExportInstance.prototype.getFormatOptionText = function(format) {
        if (format === constants.EXPORT_FORMATS.HTML) {
            return gettext('Web Page (Excel Dashboards)');
        } else if (format === constants.EXPORT_FORMATS.CSV) {
            return gettext('CSV (Zip file)');
        } else if (format === constants.EXPORT_FORMATS.XLS) {
            return gettext('Excel (older versions)');
        } else if (format === constants.EXPORT_FORMATS.XLSX) {
            return gettext('Excel 2007');
        }
    };

    /**
     * isNew
     *
     * Determines if an export has been saved or not
     *
     * @returns {Boolean} - Returns true if the export has been saved, false otherwise.
     */
    ExportInstance.prototype.isNew = function() {
        return !ko.utils.unwrapObservable(this._id);
    };

    ExportInstance.prototype.getSaveText = function() {
        return this.isNew() ? gettext('Create') : gettext('Save');
    };

    /**
     * save
     *
     * Saves an ExportInstance by serializing it and POSTing it
     * to the server.
     */
    ExportInstance.prototype.save = function() {
        var self = this,
            serialized;

        self.saveState(constants.SAVE_STATES.SAVING);
        serialized = self.toJS();
        $.post({
            url: self.saveUrl,
            data: JSON.stringify(serialized),
            success: function(data) {
                self.recordSaveAnalytics(function() {
                    self.saveState(constants.SAVE_STATES.SUCCESS);
                    utils.redirect(data.redirect);
                });
            },
            error: function() {
                self.saveState(constants.SAVE_STATES.ERROR);
            },
        });
    };

    /**
     * recordSaveAnalytics
     *
     * Reports to analytics what type of configurations people are saving
     * exports as.
     *
     * @param {function} callback - A funtion to be called after recording analytics.
     */
    ExportInstance.prototype.recordSaveAnalytics = function(callback) {
        var analyticsAction = this.is_daily_saved_export() ? 'Saved' : 'Regular',
            analyticsExportType = _.capitalize(this.type()),
            args,
            eventCategory;

        analytics.usage("Create Export", analyticsExportType, analyticsAction);
        if (this.export_format === constants.EXPORT_FORMATS.HTML) {
            args = ["Create Export", analyticsExportType, 'Excel Dashboard'];
            // If it's not new then we have to add the callback in to redirect
            if (!this.isNew()) {
                args.push(callback);
            }
            analytics.usage.apply(null, args);
        }
        if (this.isNew()) {
            eventCategory = constants.ANALYTICS_EVENT_CATEGORIES[this.type()];
            analytics.usage(eventCategory, 'Custom export creation', '');
            analytics.workflow("Clicked 'Create' in export edit page", callback);
        } else if (this.export_format !== constants.EXPORT_FORMATS.HTML) {
            callback();
        }
    };

    /**
     * showDeidColumn
     *
     * Makse the deid column visible and scrolls the user back to the
     * top of the export.
     */
    ExportInstance.prototype.showDeidColumn = function() {
        utils.animateToEl('#field-select', function() {
            this.isDeidColumnVisible(true);
        }.bind(this));
    };

    ExportInstance.prototype.toJS = function() {
        return ko.mapping.toJS(this, ExportInstance.mapping);
    };

    /**
     * addUserDefinedTableConfiguration
     *
     * This will add a new table to the export configuration and seed it with
     * one column, row number.
     *
     * @param {ExportInstance} instance
     * @param {Object} e - The window's click event
     */
    ExportInstance.prototype.addUserDefinedTableConfiguration = function(instance, e) {
        e.preventDefault();
        instance.tables.push(new UserDefinedTableConfiguration({
            selected: true,
            doc_type: 'TableConfiguration',
            label: 'Sheet',
            is_user_defined: true,
            path: [],
            columns: [
                {
                    doc_type: 'RowNumberColumn',
                    tags: ['row'],
                    item: {
                        doc_type: 'ExportItem',
                        path: [{
                            doc_type: 'PathNode',
                            name: 'number',
                        }]
                    },
                    selected: true,
                    is_advanced: false,
                    label: 'number',
                    deid_transform: null,
                    repeat: null,
                },
            ],
        }));
    };

    ExportInstance.mapping = {
        include: [
            '_id',
            'name',
            'tables',
            'type',
            'export_format',
            'split_multiselects',
            'transform_dates',
            'include_errors',
            'is_deidentified',
            'domain',
            'app_id',
            'case_type',
            'xmlns',
            'is_daily_saved_export',
        ],
        tables: {
            create: function(options) {
                if (options.data.is_user_defined) {
                    return new UserDefinedTableConfiguration(options.data);
                } else {
                    return new TableConfiguration(options.data);
                }
            },
        },
    };

    /**
     * TableConfiguration
     * @class
     *
     * The TableConfiguration represents one excel sheet in an export.
     * It contains a list of columns and other presentation properties
     */
    var TableConfiguration = function(tableJSON) {
        var self = this;
        // Whether or not to show advanced columns in the UI
        self.showAdvanced = ko.observable(false);
        ko.mapping.fromJS(tableJSON, TableConfiguration.mapping, self);
    };

    TableConfiguration.prototype.isVisible = function() {
        // Not implemented
        return true;
    };

    TableConfiguration.prototype.toggleShowAdvanced = function(table) {
        table.showAdvanced(!table.showAdvanced());
    };

    TableConfiguration.prototype._select = function(select) {
        _.each(this.columns(), function(column) {
            column.selected(select && column.isVisible(this));
        }.bind(this));
    };

    /**
     * selectAll
     *
     * @param {TableConfiguration} table
     *
     * Selects all visible columns in the table.
     */
    TableConfiguration.prototype.selectAll = function(table) {
        table._select(true);
    };

    /**
     * selectNone
     *
     * @param {TableConfiguration} table
     *
     * Deselects all visible columns in the table.
     */
    TableConfiguration.prototype.selectNone = function(table) {
        table._select(false);
    };

    /**
     * useLabels
     *
     * @param {TableConfiguration} table
     *
     * Uses the question labels for the all the label values in the column.
     */
    TableConfiguration.prototype.useLabels = function(table) {
        _.each(table.columns(), function(column) {
            if (column.isQuestion() && !column.isUserDefined) {
                column.label(column.item.label() || column.label());
            }
        });
    };

    /**
     * useIds
     *
     * @param {TableConfiguration} table
     *
     * Uses the question ids for the all the label values in the column.
     */
    TableConfiguration.prototype.useIds = function(table) {
        _.each(table.columns(), function(column) {
            if (column.isQuestion() && !column.isUserDefined) {
                column.label(column.item.readablePath() || column.label());
            }
        });
    };

    TableConfiguration.prototype.getColumn = function(path) {
        return _.find(this.columns(), function(column) {
            return utils.readablePath(column.item.path()) === path;
        });
    };

    TableConfiguration.prototype.addUserDefinedExportColumn = function(table, e) {
        e.preventDefault();
        table.columns.push(new UserDefinedExportColumn({
            selected: true,
            is_editable: true,
            deid_transform: null,
            doc_type: 'UserDefinedExportColumn',
            label: '',
            custom_path: [],
        }));
    };

    TableConfiguration.mapping = {
        include: ['name', 'path', 'columns', 'selected', 'label', 'is_deleted', 'doc_type', 'is_user_defined'],
        columns: {
            create: function(options) {
                if (options.data.doc_type === 'UserDefinedExportColumn') {
                    return new UserDefinedExportColumn(options.data);
                } else {
                    return new ExportColumn(options.data);
                }
            },
        },
        path: {
            create: function(options) {
                return new PathNode(options.data);
            },
        },
    };

    /**
     * UserDefinedTableConfiguration
     * @class
     *
     * This represents a table configuration that has been defined by the user. It
     * is very similar to a TableConfiguration except that the user defines the
     * path to where the new sheet should be.
     *
     * The customPathString for a table should always end in [] since a new export
     * table should be an array.
     *
     * When specifying questions/properties in a user defined table, you'll need
     * to include the base table path in the property. For example:
     *
     * table path: form.repeat[]
     * question path: form.repeat[].question1
     */
    var UserDefinedTableConfiguration = function(tableJSON) {
        var self = this;
        ko.mapping.fromJS(tableJSON, TableConfiguration.mapping, self);
        self.customPathString = ko.observable(utils.readablePath(self.path()));
        self.customPathString.extend({
            required: true,
            pattern: {
                message: gettext('The table path should end with []'),
                params: /^.*\[\]$/,
            },
        });

        self.showAdvanced = ko.observable(false);
        self.customPathString.subscribe(self.onCustomPathChange.bind(self));
    };
    UserDefinedTableConfiguration.prototype = Object.create(TableConfiguration.prototype);

    UserDefinedTableConfiguration.prototype.onCustomPathChange = function() {
        var rowColumn,
            nestedRepeatCount;
        this.path(utils.customPathToNodes(this.customPathString()));

        // Update the rowColumn's repeat count by counting the number of
        // repeats in the table path
        rowColumn = this.getColumn('number');
        if (rowColumn) {
            nestedRepeatCount = _.filter(this.path(), function(node) { return node.is_repeat(); }).length;
            rowColumn.repeat(nestedRepeatCount);
        }
    };

     /**
     * ExportColumn
     * @class
     *
     * The model that represents a column in an export. Each column has a one-to-one
     * mapping with an ExportItem. The column controls the presentation of that item.
     */
    var ExportColumn = function(columnJSON) {
        var self = this;
        ko.mapping.fromJS(columnJSON, ExportColumn.mapping, self);
        // showOptions is used a boolean for whether to show options for user defined option
        // lists. This is used for the feature preview SPLIT_MULTISELECT_CASE_EXPORT
        self.showOptions = ko.observable(false);
        self.userDefinedOptionToAdd = ko.observable('');
        self.isUserDefined = false;
    };

    /**
     * isQuestion
     *
     * @returns {Boolean} - Returns true if the column is associated with a form question
     *      or a case property, false otherwise.
     */
    ExportColumn.prototype.isQuestion = function() {
        var disallowedTags = ['info', 'case', 'server', 'row', 'app', 'stock'],
            self = this;
        return !_.any(disallowedTags, function(tag) { return _.include(self.tags(), tag); });
    };


    /**
     * addUserDefinedOption
     *
     * This adds an options to the user defined options. This is used for the
     * feature preview: SPLIT_MULTISELECT_CASE_EXPORT
     */
    ExportColumn.prototype.addUserDefinedOption = function() {
        var option = this.userDefinedOptionToAdd();
        if (option) {
            this.user_defined_options.push(option);
        }
        this.userDefinedOptionToAdd('');
    };

    /**
     * removeUserDefinedOption
     *
     * Removes a user defined option.
     */
    ExportColumn.prototype.removeUserDefinedOption = function(option) {
        this.user_defined_options.remove(option);
    };

    /**
     * formatProperty
     *
     * Formats a property/question for display.
     *
     * @returns {string} - Returns a string representation of the property/question
     */
    ExportColumn.prototype.formatProperty = function() {
        if (this.tags().length !== 0){
            return this.label();
        } else {
            return _.map(this.item.path(), function(node) { return node.name(); }).join('.');
        }
    };

    /**
     * getDeidOptions
     *
     * @returns {Array} - A list of all deid option choices
     */
    ExportColumn.prototype.getDeidOptions = function() {
        return _.map(constants.DEID_OPTIONS, function(value) { return value; });
    };

    /**
     * getDeidOptionText
     *
     * @param {string} deidOption - A deid option
     * @returns {string} - Given a deid option, returns the human readable label
     */
    ExportColumn.prototype.getDeidOptionText = function(deidOption) {
        if (deidOption === constants.DEID_OPTIONS.ID) {
            return gettext('Sensitive ID');
        } else if (deidOption === constants.DEID_OPTIONS.DATE) {
            return gettext('Sensitive Date');
        } else if (deidOption === constants.DEID_OPTIONS.NONE) {
            return gettext('None');
        }
    };

    /**
     * isVisible
     *
     * Determines whether the column is visible to the user.
     *
     * @returns {Boolean} - True if the column is visible false otherwise.
     */
    ExportColumn.prototype.isVisible = function(table) {
        return table.showAdvanced() || (!this.is_advanced() || this.selected());
    };

    /**
     * isCaseName
     *
     * Checks to see if the column is the name of the case property
     *
     * @returns {Boolean} - True if it is the case name property False otherwise.
     */
    ExportColumn.prototype.isCaseName = function() {
        return this.item.isCaseName();
    };

    ExportColumn.prototype.translatedHelp = function() {
        return gettext(this.help_text);
    };

    ExportColumn.prototype.isEditable = function() {
        return false;
    };

    ExportColumn.mapping = {
        include: [
            'item',
            'label',
            'is_advanced',
            'selected',
            'tags',
            'deid_transform',
            'help_text',
            'split_type',
            'user_defined_options',
        ],
        item: {
            create: function(options) {
                return new ExportItem(options.data);
            },
        },
    };

    /*
     * UserDefinedExportColumn
     *
     * This model represents a column that a user has defined the path to the
     * data within the form. It should only be needed for RemoteApps
     */
    var UserDefinedExportColumn = function(columnJSON) {
        var self = this;
        ko.mapping.fromJS(columnJSON, UserDefinedExportColumn.mapping, self);
        self.showOptions = ko.observable(false);
        self.isUserDefined = true;
        self.customPathString = ko.observable(utils.readablePath(self.custom_path())).extend({
            required: true,
        });
        self.customPathString.subscribe(self.customPathToNodes.bind(self));
    };
    UserDefinedExportColumn.prototype = Object.create(ExportColumn.prototype);

    UserDefinedExportColumn.prototype.isVisible = function() {
        return true;
    };

    UserDefinedExportColumn.prototype.formatProperty = function() {
        return _.map(this.custom_path(), function(node) { return node.name(); }).join('.');
    };

    UserDefinedExportColumn.prototype.isEditable = function() {
        return this.is_editable();
    };

    UserDefinedExportColumn.prototype.customPathToNodes = function() {
        this.custom_path(utils.customPathToNodes(this.customPathString()));
    };

    UserDefinedExportColumn.mapping = {
        include: [
            'selected',
            'deid_transform',
            'doc_type',
            'custom_path',
            'label',
            'is_editable',
        ],
        custom_path: {
            create: function(options) {
                return new PathNode(options.data);
            },
        },
    };

    /**
     * ExportItem
     * @class
     *
     * An item for export that is generated from the schema generation
     */
    var ExportItem = function(itemJSON) {
        var self = this;
        ko.mapping.fromJS(itemJSON, ExportItem.mapping, self);
    };

    /**
     * isCaseName
     *
     * Checks to see if the item is the name of the case
     *
     * @returns {Boolean} - True if it is the case name property False otherwise.
     */
    ExportItem.prototype.isCaseName = function() {
        return this.path()[this.path().length - 1].name === 'name';
    };

    ExportItem.prototype.readablePath = function() {
        return utils.readablePath(this.path());
    };

    ExportItem.mapping = {
        include: ['path', 'label', 'tag'],
        path: {
            create: function(options) {
                return new PathNode(options.data);
            },
        },
    };

    /**
     * PathNode
     * @class
     *
     * An node representing a portion of the path to item to export.
     */
    var PathNode = function(pathNodeJSON) {
        ko.mapping.fromJS(pathNodeJSON, PathNode.mapping, this);
    };

    PathNode.mapping = {
        include: ['name', 'is_repeat'],
    };

    return {
        ExportInstance: ExportInstance,
        ExportColumn: ExportColumn,
        ExportItem: ExportItem,
        PathNode: PathNode,
    };

});
