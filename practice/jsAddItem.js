(function(){

    mainModule = {

        addCountryBtn : document.getElementById('addCountryBtn'),
        countryInput : document.getElementById('countryInput'),
        countryUl : document.getElementById('countryNamesUl'),
        addImageBtn : document.getElementById('addImageBtn'),
        previewDiv :   document.getElementById('div-preview'),
        imgTag : document.getElementById('img-preview'),

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

        },

        uploadImage : function(files){
            console.log(files);
            let fileNames = [];
            let uploadSize = 0;
            
            for( file of files){
                uploadSize += file.size;
                fileNames.push(file.name)
            }
            if(uploadSize > 20971520  ){
                alert('20MB 초과하는 이미지는 업로드 불가')
                return;
            }
            console.log(files[0]);
            const fileName = files[0].name;
            this.previewDiv.innerHTMl = '';

            const pageOrigin = window.location.origin;
            const newImgSrc = `${pageOrigin}/img/${fileName}`;
            
            this.imgTag.src = newImgSrc;
            
            
        },
        getImage : function(fileName){
            const folderPath = window.location.origin + '/img/';
            console.log('wow');
        }
    }

})();


addCountryBtn.addEventListener('click', () => {
    
    mainModule.addCountry(countryInput.value);
    
});


removeCountryBtn.addEventListener('click', () => {
    mainModule.removeCountry(countryInput.value);
});

addImageBtn.addEventListener('change', () => {
    // mainModule.uploadImage(addImageBtn.files);
    mainModule.getImage(addImageBtn.files);
});
