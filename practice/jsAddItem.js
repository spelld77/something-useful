(function(){

    mainModule = {

        addCountryBtn : document.getElementById('addCountryBtn'),
        countryInput : document.getElementById('countryInput'),
        countryUl : document.getElementById('countryNamesUl'),

        getCountries : function(){
            const countriesLis = [...this.countryUl.children];
            let countries = [];
            countriesLis.forEach( li => {
                countries.push(li.textContent);
            });
            return countries;
        },

        isDuplicateCountry: function(newCountry){

            const nowCountries = this.getCountries();
            return nowCountries.some(nowCountry => {
                return nowCountry.toUpperCase() == newCountry.toUpperCase();
            });
            
        },

        addCountry : function(countryName){
            
            const isDuplicate = this.isDuplicateCountry(countryName)
            if(isDuplicate) return;

            var newLi = document.createElement('li');
            newLi.textContent = countryName;
            countryNamesUl.appendChild(newLi);

        },
        removeCountry : function(inputCountryName){
          
            countryLis = document.querySelectorAll('#countryNamesUl li');
            const countryNames = this.getCountries();

            countryLis.forEach(country => {
                countryName =country.textContent;
                if(countryName == inputCountryName){
                    country.remove();
                }
            });

        }
    }

})();


addCountryBtn.addEventListener('click', () => {
    
    mainModule.addCountry(countryInput.value);
    
});


removeCountryBtn.addEventListener('click', () => {
    mainModule.removeCountry(countryInput.value);
});

