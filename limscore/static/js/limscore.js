$(function () {    

    // Disable normal fwd/back button navigation. This type of navigation is
    // expected behaviour on the web but is unexpected in a desktop application
    // which we are simulating. url_fwd/url_back routing functions instead
    // give us whar we need.
    history.pushState(null, null, location.href);
    window.onpopstate = function() {
        history.go(1);
        };

    
    // Only allow a form to be submitted once. Should have sufficient logic
    // to prevent dara corruption if multiple submissions but this ensures
    // that the response the user sees reflects the first submission.
    $('form').one('submit', function() {  
        $(this).find('input[type="submit"]').attr('disabled', true);
        return true;
        });


    // Lazy load dropdown menus.
    $('.has-dropdown').one('mouseenter', function() {
        $(this).children('.navbar-dropdown').load($(this).attr('data-href'));
        return true;
        });

    
    // Prevent accidental dragging of elements as looks ugly.
    $('body').on('ondragstart', function() {
        return false;
        });
    
    
    // Enable clickable table rows.
    $('tr[data-href]').on('click', function() {
        // Only a problem with slow loads to a view that updates the cache
        $('tr[data-href]').off('click');
        window.location = $(this).attr('data-href');
        return false;
        });
    
    
    // Enable table sort.
    $('table.is-sortable').tablesort();

    });

        
        
