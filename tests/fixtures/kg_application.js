(function (Application, $, undefined) {
    'use strict';

    Application.culture = '';
    Application.neutralCulture = '';

    Application.CldrFetch = '';

    Application.init = function () {

        Application.loadCulture(Application.culture);

        $.validator.methods.number = function (value, element) {
            var number = Globalize.parseNumber(value);
            return this.optional(element) || jQuery.isNumeric(Globalize.parseNumber(value));
        };

        $.validator.methods.date = function (value, element) {
            return (this.optional(element) || Globalize.parseDate(value));
        };

        jQuery.extend(jQuery.validator.methods, {
            range: function (value, element, param) {
                var val = Globalize.parseNumber(value);
                return this.optional(element) || (val >= param[0] && val <= param[1]);
            }
        });

        $.ajaxSetup({
            error: function (jqXHR, exception) {
                var errMsg = '';
                //if (jqXHR.status === 0) {
                //    //errMsg = 'Not connected.  Please verify network.';
                //}
                if (jqXHR.status === 404) {
                    errMsg = 'Requested page not found. [404]';
                } else if (jqXHR.status === 500) {
                    errMsg = 'Internal Server Error [500].';
                } else if (exception === 'parsererror') {
                    errMsg = 'Requested JSON parse failed.';
                } else if (exception === 'timeout') {
                    errMsg = 'Time out error.';
                } else if (exception === 'abort') {
                    errMsg = 'Ajax request aborted.';
                } else {
                    errMsg = 'Uncaught Error.\n' + jqXHR.responseText;
                }
                if ((errMsg) && ((errMsg) !== '')) {
                    alert(errMsg);
                }
            },
            timeout: 240000  // 240 sec default
        });

    };

    Application.loadCulture = function (culture) {

        $.when(
          $.get(Application.CldrFetch + '/' + culture + '/' + encodeURIComponent("likelySubtags")),
          $.get(Application.CldrFetch + '/' + culture + '/' + "numberingSystems"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "plurals"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "ordinals"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "currencyData"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "timeData"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "weekData"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "ca-gregorian"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "timeZoneNames"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "numbers"),
          $.get(Application.CldrFetch + '/' + culture + '/' + "currencies")
        )
        .then(function () {
            // Normalize $.get results, we only need the JSON, not the request statuses.
            return [].slice.apply(arguments, [0]).map(function (result) {
                return result[0];
            });

        }).then(Globalize.load).then(function () {
            Globalize.locale(culture);
        });
    };

}(window.Application = window.Application || {}, jQuery));